"""Strategy seam.

A strategy is a pure function of candle history to a desired exposure. It
never places orders, never reads account state, and never talks to Telegram.
Swapping strategies must not require touching any other component.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.models import Candle, Signal


@runtime_checkable
class Strategy(Protocol):
    name: str

    @property
    def warmup(self) -> int:
        """Number of candles required before signals are meaningful."""
        ...

    def evaluate(self, candles: list[Candle]) -> Signal | None:
        """Return the exposure this strategy wants, or None to abstain."""
        ...
