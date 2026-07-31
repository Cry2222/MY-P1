"""Risk seam — the only component allowed to authorise an order.

Every order passes through `assess`. There is no bypass path, and the engine
denies by default: if a limit cannot be evaluated, the order is rejected
rather than allowed through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import RiskConfig
from ..core.models import Exposure, Position, RiskDecision, Signal

log = logging.getLogger(__name__)

KILL_KEY = "kill_switch"
PAUSE_KEY = "paused"


@dataclass
class RiskState:
    """Everything the engine needs to decide, gathered by the caller."""

    equity: float
    realized_pnl_today: float
    orders_today: int
    killed: bool = False
    paused: bool = False


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        config.validate()
        self.config = config

    def size_for(self, equity: float, price: float) -> float:
        """Quantity to open with, capped by both the fraction and the notional."""
        if price <= 0:
            return 0.0
        budget = min(equity * self.config.risk_fraction, self.config.max_position_notional)
        return max(budget / price, 0.0)

    def assess(
        self,
        signal: Signal,
        position: Position,
        state: RiskState,
        *,
        is_exit: bool = False,
    ) -> RiskDecision:
        """Approve or deny the trade implied by `signal` given `position`.

        Exits are held to a narrower set of checks than entries: a hard stop
        must never trap the bot in a position it is trying to leave.
        """
        if state.killed:
            # The kill switch stops entries and exits alike. It exists so a
            # human can freeze the bot completely and unwind by hand.
            return RiskDecision(False, 0.0, "kill switch engaged")

        if is_exit:
            if position.is_flat:
                return RiskDecision(False, 0.0, "already flat")
            return RiskDecision(True, abs(position.quantity), "exit approved")

        if state.paused:
            return RiskDecision(False, 0.0, "trading paused")

        if signal.target is Exposure.FLAT:
            return RiskDecision(False, 0.0, "no exposure requested")

        if state.realized_pnl_today <= -abs(self.config.max_daily_loss):
            return RiskDecision(
                False, 0.0,
                f"daily loss limit hit ({state.realized_pnl_today:.2f} "
                f"<= -{self.config.max_daily_loss:.2f})",
            )

        if state.orders_today >= self.config.max_orders_per_day:
            return RiskDecision(
                False, 0.0,
                f"daily order cap hit ({state.orders_today}/{self.config.max_orders_per_day})",
            )

        if not position.is_flat:
            return RiskDecision(False, 0.0, "position already open")

        if signal.price <= 0:
            return RiskDecision(False, 0.0, "invalid signal price")

        if state.equity <= 0:
            return RiskDecision(False, 0.0, "no equity available")

        quantity = self.size_for(state.equity, signal.price)
        notional = quantity * signal.price

        if notional < self.config.min_order_notional:
            return RiskDecision(
                False, 0.0,
                f"order too small ({notional:.2f} < {self.config.min_order_notional:.2f})",
            )

        if notional > self.config.max_position_notional + 1e-9:
            quantity = self.config.max_position_notional / signal.price
            notional = quantity * signal.price

        if notional > state.equity:
            return RiskDecision(False, 0.0, "order exceeds available equity")

        return RiskDecision(True, quantity, f"approved {notional:.2f} notional")

    def check_slippage(self, expected: float, actual: float) -> RiskDecision:
        """Reject a fill that came back too far from the signalled price."""
        if expected <= 0:
            return RiskDecision(False, 0.0, "invalid expected price")
        drift = abs(actual - expected) / expected * 100
        if drift > self.config.max_slippage_pct:
            return RiskDecision(
                False, 0.0,
                f"slippage {drift:.3f}% exceeds {self.config.max_slippage_pct:.3f}%",
            )
        return RiskDecision(True, 0.0, f"slippage {drift:.3f}%")
