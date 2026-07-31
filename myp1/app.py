"""Composition root.

Chooses concrete implementations for each seam based on config, wires them
into the runner, and manages startup/shutdown. This is the only module that
knows about every component at once — which is what keeps the components
from knowing about each other.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .config import Config, ConfigError, load_config
from .execution.base import ExecutionVenue
from .execution.paper import PaperVenue
from .gateway.telegram_bot import TelegramGateway
from .marketdata.base import MarketDataSource
from .marketdata.ccxt_source import CcxtMarketData
from .risk.engine import RiskEngine
from .runner import TradingRunner
from .state.journal import Journal
from .strategy.base import Strategy
from .strategy.ema_cross import EmaCrossStrategy

log = logging.getLogger(__name__)


def build_strategy(config: Config) -> Strategy:
    if config.strategy == "ema_cross":
        return EmaCrossStrategy(
            config.fast_period, config.slow_period, long_only=config.long_only
        )
    raise ValueError(f"Unknown strategy {config.strategy!r}")


def build_venue(config: Config) -> ExecutionVenue:
    if config.is_live:
        from .execution.live import LiveVenue

        return LiveVenue(
            config.exchange,
            config.api_key or "",
            config.api_secret or "",
            armed=True,  # config.validate() already enforced the confirm phrase
        )
    return PaperVenue(
        config.starting_cash,
        fee_pct=config.fee_pct,
        slippage_pct=config.slippage_pct,
        allow_short=not config.long_only,
    )


def build_market_data(config: Config) -> MarketDataSource:
    return CcxtMarketData(config.exchange)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


async def run(config: Config | None = None) -> None:
    config = config or load_config()
    configure_logging(config.log_level)

    journal = Journal(config.journal_path)
    runner = TradingRunner(
        config,
        market_data=build_market_data(config),
        strategy=build_strategy(config),
        risk=RiskEngine(config.risk),
        venue=build_venue(config),
        journal=journal,
    )

    gateway: TelegramGateway | None = None
    if config.telegram.usable:
        gateway = TelegramGateway(config.telegram, runner)
        runner.notifier = gateway.send
    else:
        log.warning("Telegram disabled — no remote kill switch. Paper mode only.")

    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()

    def request_stop() -> None:
        log.info("shutdown signal received")
        runner.stop()
        stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:  # pragma: no cover - non-POSIX
            pass

    try:
        if gateway is not None:
            await gateway.start()
        await runner.run()
    finally:
        runner.stop()
        if gateway is not None:
            try:
                await gateway.stop()
            except Exception:
                log.exception("gateway shutdown failed")
        await runner.venue.close()
        await runner.market_data.close()
        journal.close()
        log.info("shutdown complete")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except ConfigError as exc:
        # Misconfiguration is an operator error, not a crash. Say what is
        # wrong on one line instead of burying it in a traceback.
        print(f"config error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
