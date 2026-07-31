"""The trading loop.

This is the only place components meet. It owns no strategy logic, no risk
rules and no venue detail — it moves data across the seams in a fixed order:

    market data -> strategy -> position diff -> risk -> execution -> journal -> notify

Every ordering decision in that pipeline exists for a reason. Risk sits
between the strategy and the venue so no signal can reach an exchange
unchecked, and the journal is written before notification so a crash cannot
lose a fill that already happened.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .config import Config
from .core.models import Candle, Exposure, Fill, Order, Position, Side, Signal
from .execution.base import ExecutionError, ExecutionVenue
from .marketdata.base import MarketDataSource
from .risk.engine import KILL_KEY, PAUSE_KEY, RiskEngine, RiskState
from .state.journal import Journal, today
from .strategy.base import Strategy

log = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]


class SupportsSeed(Protocol):
    def seed_inventory(self, symbol: str, quantity: float, cash: float) -> None: ...


@dataclass
class TickResult:
    """What one pass of the loop did, returned for tests and diagnostics."""

    signal: Signal | None = None
    order: Order | None = None
    fill: Fill | None = None
    rejected: str = ""
    note: str = ""


class TradingRunner:
    def __init__(
        self,
        config: Config,
        *,
        market_data: MarketDataSource,
        strategy: Strategy,
        risk: RiskEngine,
        venue: ExecutionVenue,
        journal: Journal,
        notifier: Notifier | None = None,
    ) -> None:
        self.config = config
        self.market_data = market_data
        self.strategy = strategy
        self.risk = risk
        self.venue = venue
        self.journal = journal
        self.notifier = notifier

        self.symbol = config.symbol
        self.position: Position = journal.rebuild_position(self.symbol)
        self.last_price: float = 0.0
        self.last_tick_at: int = 0
        self.started_at: int = int(time.time() * 1000)
        self.ticks: int = 0
        self.errors: int = 0
        self._running = False

        self._restore_venue_state()

    # -- lifecycle ------------------------------------------------------

    def _restore_venue_state(self) -> None:
        """Rebuild simulator inventory from journalled fills after a restart."""
        seed = getattr(self.venue, "seed_inventory", None)
        if not callable(seed) or self.venue.is_live:
            return
        fills = self.journal.fill_count()
        if fills == 0:
            return
        cash = self.config.starting_cash
        for row in self.journal.recent_fills(limit=10_000):
            notional = row["quantity"] * row["price"]
            cash += (-notional if row["side"] == Side.BUY.value else notional) - row["fee"]
        seed(self.symbol, self.position.quantity, cash)
        log.info(
            "restored paper state from %d fills: qty=%.8f cash=%.2f",
            fills, self.position.quantity, cash,
        )

    @property
    def killed(self) -> bool:
        return bool(self.journal.get_control(KILL_KEY, False))

    @property
    def paused(self) -> bool:
        return bool(self.journal.get_control(PAUSE_KEY, False))

    def kill(self, reason: str = "manual") -> None:
        self.journal.set_control(KILL_KEY, True)
        log.warning("KILL SWITCH ENGAGED (%s)", reason)

    def revive(self) -> None:
        self.journal.set_control(KILL_KEY, False)
        log.warning("kill switch released")

    def pause(self) -> None:
        self.journal.set_control(PAUSE_KEY, True)

    def resume(self) -> None:
        self.journal.set_control(PAUSE_KEY, False)

    # -- one pass -------------------------------------------------------

    async def tick(self) -> TickResult:
        """Run exactly one pass of the pipeline."""
        self.ticks += 1
        self.last_tick_at = int(time.time() * 1000)

        candles = await self.market_data.fetch_candles(
            self.symbol, self.config.timeframe, limit=max(self.strategy.warmup + 50, 100)
        )
        if not candles:
            return TickResult(note="no candles")

        self.last_price = candles[-1].close

        signal = self.strategy.evaluate(candles)
        if signal is None:
            return TickResult(note="strategy abstained")
        self.journal.record_signal(signal)

        order, is_exit = self._plan(signal)
        if order is None:
            return TickResult(signal=signal, note="target already held")

        state = await self._risk_state(candles[-1])
        decision = self.risk.assess(signal, self.position, state, is_exit=is_exit)
        if not decision.approved:
            self.journal.record_order(order, "rejected", decision.reason)
            log.info("order rejected: %s", decision.reason)
            return TickResult(signal=signal, order=order, rejected=decision.reason)

        order = Order(
            symbol=order.symbol,
            side=order.side,
            quantity=decision.quantity,
            price=order.price,
            reason=order.reason,
            client_id=order.client_id,
        )

        try:
            fill = await self.venue.submit(order)
        except ExecutionError as exc:
            self.errors += 1
            self.journal.record_order(order, "failed", str(exc))
            log.error("execution failed: %s", exc)
            await self._notify(f"⚠️ Order failed: {exc}")
            return TickResult(signal=signal, order=order, rejected=str(exc))

        slippage = self.risk.check_slippage(order.price, fill.price)
        if not slippage.approved:
            # The fill already happened; this cannot undo it. Record it,
            # then stop trading so a human looks at why prices are moving
            # this far between signal and execution.
            log.error("slippage breach on filled order: %s", slippage.reason)
            await self._commit(fill, order)
            self.kill(f"slippage breach: {slippage.reason}")
            await self._notify(f"🛑 Kill switch engaged — {slippage.reason}")
            return TickResult(signal=signal, order=order, fill=fill, rejected=slippage.reason)

        await self._commit(fill, order)
        return TickResult(signal=signal, order=order, fill=fill)

    def _plan(self, signal: Signal) -> tuple[Order | None, bool]:
        """Derive the order that moves the live position to the signal target."""
        current = self.position.exposure
        target = signal.target
        if current is target:
            return None, False

        client_id = uuid.uuid4().hex[:12]

        # Leaving an open position always takes priority over entering a new
        # one. A reversal is executed as an exit now and an entry next tick,
        # so a single order never crosses through zero.
        if not self.position.is_flat:
            side = Side.SELL if current is Exposure.LONG else Side.BUY
            return Order(
                symbol=self.symbol,
                side=side,
                quantity=abs(self.position.quantity),
                price=signal.price,
                reason=f"exit {current.value}: {signal.reason}",
                client_id=client_id,
            ), True

        if target is Exposure.FLAT:
            return None, False

        side = Side.BUY if target is Exposure.LONG else Side.SELL
        return Order(
            symbol=self.symbol,
            side=side,
            quantity=0.0,  # risk engine sets the real size
            price=signal.price,
            reason=f"enter {target.value}: {signal.reason}",
            client_id=client_id,
        ), False

    async def _risk_state(self, candle: Candle) -> RiskState:
        try:
            equity = await self.venue.equity(candle.close)
        except ExecutionError as exc:
            log.error("equity lookup failed: %s", exc)
            equity = 0.0  # denies new entries; exits stay permitted
        return RiskState(
            equity=equity,
            realized_pnl_today=self.journal.realized_pnl(today()),
            orders_today=self.journal.order_count(today()),
            killed=self.killed,
            paused=self.paused,
        )

    async def _commit(self, fill: Fill, order: Order) -> None:
        realized = self.position.apply(fill)
        self.journal.record_fill(fill, realized)
        self.journal.record_order(order, "filled", f"realized {realized:.4f}")
        arrow = "🟢" if fill.side is Side.BUY else "🔴"
        await self._notify(
            f"{arrow} {fill.side.value.upper()} {fill.quantity:.8f} {fill.symbol}\n"
            f"price {fill.price:.4f} · fee {fill.fee:.4f}\n"
            f"realized {realized:+.4f} · position {self.position.quantity:.8f}"
        )

    async def _notify(self, text: str) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier(text)
        except Exception:  # notification must never break the trading loop
            log.exception("notifier failed")

    # -- long-running loop ----------------------------------------------

    async def run(self, *, max_ticks: int | None = None) -> None:
        self._running = True
        mode = "LIVE" if self.config.is_live else "paper"
        log.info("runner started in %s mode on %s %s via %s",
                 mode, self.symbol, self.config.timeframe, self.venue.name)
        await self._notify(
            f"▶️ MY-P1 started — {mode} · {self.symbol} {self.config.timeframe} "
            f"· {self.strategy.name}"
        )

        completed = 0
        try:
            while self._running:
                if max_ticks is not None and completed >= max_ticks:
                    break
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.errors += 1
                    log.exception("tick failed")
                    if self.errors >= 10:
                        self.kill("too many consecutive errors")
                        await self._notify("🛑 Kill switch engaged — repeated tick failures")
                        break
                completed += 1
                if max_ticks is None or completed < max_ticks:
                    await asyncio.sleep(self.config.poll_seconds)
        finally:
            self._running = False
            log.info("runner stopped after %d ticks", completed)

    def stop(self) -> None:
        self._running = False

    # -- reporting ------------------------------------------------------

    def status(self) -> dict:
        uptime = (int(time.time() * 1000) - self.started_at) / 1000
        return {
            "mode": "live" if self.config.is_live else "paper",
            "venue": self.venue.name,
            "symbol": self.symbol,
            "timeframe": self.config.timeframe,
            "strategy": self.strategy.name,
            "running": self._running,
            "killed": self.killed,
            "paused": self.paused,
            "ticks": self.ticks,
            "errors": self.errors,
            "uptime_seconds": round(uptime, 1),
            "last_price": self.last_price,
            "position_qty": self.position.quantity,
            "position_side": self.position.exposure.value,
            "avg_price": self.position.avg_price,
            "unrealized": self.position.unrealized_pnl(self.last_price),
            "realized_today": self.journal.realized_pnl(today()),
            "realized_total": self.journal.realized_pnl(),
            "orders_today": self.journal.order_count(today()),
        }
