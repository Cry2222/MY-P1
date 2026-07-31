"""Market data seam.

Anything that can produce candles for a symbol satisfies this protocol. The
runner never learns whether candles came from an exchange, a CSV replay, or
a fixture in a test.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.models import Candle


@runtime_checkable
class MarketDataSource(Protocol):
    name: str

    async def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        """Return up to `limit` closed candles, oldest first."""
        ...

    async def close(self) -> None:
        """Release any network resources."""
        ...
