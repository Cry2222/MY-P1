"""Reference strategy: exponential moving-average crossover.

Included so the pipeline has something real to run end to end. It is a
demonstration of the seam, not a recommendation — replace it with your own
edge and the rest of the system is unchanged.
"""

from __future__ import annotations

from ..core.models import Candle, Exposure, Signal
from .indicators import ema


class EmaCrossStrategy:
    def __init__(
        self, fast_period: int = 12, slow_period: int = 26, *, long_only: bool = True
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period")
        self.name = f"ema_cross({fast_period},{slow_period})"
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.long_only = long_only

    @property
    def warmup(self) -> int:
        # Slow EMA needs `slow_period` bars to seed, plus one to have a prior
        # value to compare against for a crossover.
        return self.slow_period + 1

    def evaluate(self, candles: list[Candle]) -> Signal | None:
        if len(candles) < self.warmup:
            return None

        closes = [c.close for c in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        if len(fast) < 2 or len(slow) < 2:
            return None

        # The two series start at different offsets; align on their tails.
        fast_now, fast_prev = fast[-1], fast[-2]
        slow_now, slow_prev = slow[-1], slow[-2]

        last = candles[-1]
        spread = fast_now - slow_now
        prev_spread = fast_prev - slow_prev

        if spread > 0:
            target = Exposure.LONG
        elif self.long_only:
            target = Exposure.FLAT
        else:
            target = Exposure.SHORT

        crossed = (spread > 0) != (prev_spread > 0)
        reason = (
            f"fast={fast_now:.4f} slow={slow_now:.4f} "
            f"{'crossover' if crossed else 'trend'}"
        )
        # Confidence scales with how separated the averages are, normalised by
        # price so it is comparable across symbols.
        confidence = min(1.0, abs(spread) / last.close * 100) if last.close else 0.0

        return Signal(
            symbol=last.symbol,
            target=target,
            price=last.close,
            timestamp=last.timestamp,
            reason=reason,
            confidence=confidence,
        )
