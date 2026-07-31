"""Domain types shared across every component.

These are the only objects allowed to cross a component seam. Market data,
strategy, risk, execution and the gateway all speak in terms of what is
defined here, which is what lets any one of them be replaced without
touching the others.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Exposure(StrEnum):
    """Target market exposure a strategy wants to hold.

    Strategies declare the position they want, not the trade to get there.
    The runner diffs the target against the live position and derives the
    order, so a strategy that repeats the same signal cannot double-enter.
    """

    LONG = "long"
    FLAT = "flat"
    SHORT = "short"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: int  # milliseconds since epoch, candle open time
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def seconds(self) -> float:
        return self.timestamp / 1000.0


@dataclass(frozen=True)
class Signal:
    symbol: str
    target: Exposure
    price: float
    timestamp: int
    reason: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    quantity: float
    price: float  # reference price; market orders fill near this
    reason: str = ""
    client_id: str = ""


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    timestamp: int
    venue: str
    order_ref: str = ""

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0  # signed: positive long, negative short
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def exposure(self) -> Exposure:
        if self.quantity > 0:
            return Exposure.LONG
        if self.quantity < 0:
            return Exposure.SHORT
        return Exposure.FLAT

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0.0

    def unrealized_pnl(self, mark: float) -> float:
        if self.is_flat:
            return 0.0
        return (mark - self.avg_price) * self.quantity

    def apply(self, fill: Fill) -> float:
        """Fold a fill into this position, returning realized PnL from it."""
        signed = fill.quantity if fill.side is Side.BUY else -fill.quantity
        realized = 0.0

        if self.quantity == 0 or (self.quantity > 0) == (signed > 0):
            # Opening or adding: weighted-average the entry price.
            total = self.quantity + signed
            if total != 0:
                self.avg_price = (
                    self.avg_price * self.quantity + fill.price * signed
                ) / total
            self.quantity = total
        else:
            # Reducing, closing, or flipping.
            closing = min(abs(signed), abs(self.quantity))
            direction = 1.0 if self.quantity > 0 else -1.0
            realized = (fill.price - self.avg_price) * closing * direction
            self.quantity += signed
            if self.quantity == 0:
                self.avg_price = 0.0
            elif (self.quantity > 0) != (direction > 0):
                # Flipped through zero; the remainder opens at the fill price.
                self.avg_price = fill.price

        realized -= fill.fee
        self.realized_pnl += realized
        return realized


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    quantity: float = 0.0
    reason: str = ""


@dataclass
class AccountSnapshot:
    equity: float
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    taken_at: int = field(default_factory=lambda: int(time.time() * 1000))
