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
from typing import TYPE_CHECKING, Any

from .config import Config, ConfigError, load_config
from .execution.base import ExecutionVenue
from .execution.paper import PaperVenue
from .marketdata.base import MarketDataSource
from .marketdata.ccxt_source import CcxtMarketData
from .risk.engine import RiskEngine
from .runner import TradingRunner
from .state.journal import Journal
from .strategy.base import Strategy
from .strategy.ema_cross import EmaCrossStrategy

if TYPE_CHECKING:
    from .gateway.telegram_bot import TelegramGateway

log = logging.getLogger(__name__)


def build_gateway(config: Config, runner: TradingRunner) -> TelegramGateway | None:
    """Build the Telegram gateway, or None when it is unavailable.

    Imported lazily because python-telegram-bot is an optional dependency: an
    on-device install under Termux often cannot build it, and the mobile app
    is the control surface there. A missing optional package must not stop the
    bot from starting.
    """
    if not config.telegram.usable:
        return None
    try:
        from .gateway.telegram_bot import TelegramGateway
    except ImportError:
        log.warning(
            "Telegram is configured but python-telegram-bot is not installed — "
            "continuing without it."
        )
        return None
    return TelegramGateway(config.telegram, runner)


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

    gateway: Any = build_gateway(config, runner)
    if gateway is not None:
        runner.notifier = gateway.send
    elif not config.api.enabled:
        log.warning("No Telegram and no API — this bot has no remote kill switch.")

    api_task: asyncio.Task | None = None
    if config.api.enabled:
        from .api import resolve_backend

        backend = resolve_backend(config.api.server)
        if backend == "fastapi":
            from .api.server import create_app, serve

            api_task = asyncio.create_task(
                serve(create_app(runner, config.api), config.api.host, config.api.port)
            )
        else:
            # No FastAPI, no uvicorn, no pydantic — the on-device path.
            from .api.lite import serve as serve_lite

            api_task = asyncio.create_task(serve_lite(runner, config.api))
        log.info("control API backend: %s", backend)

        if config.api.host not in {"127.0.0.1", "localhost", "::1"}:
            log.warning(
                "control API bound to %s — it is reachable beyond this host. "
                "Put it behind TLS and a private network, not just the token.",
                config.api.host,
            )

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
        if api_task is not None:
            api_task.cancel()
            try:
                await api_task
            except (asyncio.CancelledError, Exception):
                pass
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
