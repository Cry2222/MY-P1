"""Indicator maths, kept dependency-free and directly unit-testable."""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average, seeded with the first `period` SMA.

    Returns a list the same length as the input; entries before the seed is
    available are None-free by construction because they repeat the seed, so
    callers must ignore the first `period - 1` entries.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for value in values[period:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def sma(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return []
    out = []
    running = sum(values[:period])
    out.append(running / period)
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out.append(running / period)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> list[float]:
    """Average true range — used for volatility-aware position sizing."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows and closes must be the same length")
    if len(closes) <= period:
        return []

    true_ranges = []
    for i in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return sma(true_ranges, period)
