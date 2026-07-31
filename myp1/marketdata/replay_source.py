"""Deterministic candle source for backtests and tests.

Feeds a fixed history one candle at a time, so a full run of the trading loop
can be exercised with no network and no exchange.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..core.models import Candle


class ReplayMarketData:
    """Replays a pre-loaded candle series."""

    def __init__(self, candles: list[Candle], *, warmup: int = 1) -> None:
        if not candles:
            raise ValueError("ReplayMarketData needs at least one candle")
        self.name = "replay"
        self._candles = sorted(candles, key=lambda c: c.timestamp)
        self._cursor = min(warmup, len(self._candles))

    @classmethod
    def from_csv(cls, path: str | Path, symbol: str, *, warmup: int = 1) -> ReplayMarketData:
        """Load `timestamp,open,high,low,close,volume` rows from a CSV file."""
        candles: list[Candle] = []
        with Path(path).open(newline="") as handle:
            for row in csv.DictReader(handle):
                candles.append(
                    Candle(
                        symbol=symbol,
                        timestamp=int(float(row["timestamp"])),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume", 0) or 0),
                    )
                )
        return cls(candles, warmup=warmup)

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._candles)

    async def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if self.exhausted:
            return self._candles[-limit:]
        self._cursor += 1
        window = self._candles[:self._cursor]
        return window[-limit:]

    async def close(self) -> None:
        return None
