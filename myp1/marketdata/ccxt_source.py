"""Live candle feed backed by ccxt.

Only public market-data endpoints are used here, so this source works with no
API credentials at all. That is deliberate: paper mode should be able to run
against real prices without keys ever being present in the process.
"""

from __future__ import annotations

import asyncio
import logging

from ..core.models import Candle

log = logging.getLogger(__name__)


class CcxtMarketData:
    """Polls OHLCV from any ccxt-supported exchange."""

    def __init__(self, exchange_id: str = "binance", *, timeout_ms: int = 15_000) -> None:
        import ccxt  # imported lazily so the core stays testable without ccxt

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Unknown exchange {exchange_id!r}")

        self.name = f"ccxt:{exchange_id}"
        self._exchange = getattr(ccxt, exchange_id)({
            "enableRateLimit": True,
            "timeout": timeout_ms,
        })

    async def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        # ccxt's sync client blocks; keep it off the event loop.
        rows = await asyncio.to_thread(
            self._exchange.fetch_ohlcv, symbol, timeframe, None, limit
        )
        candles = [
            Candle(
                symbol=symbol,
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
        # The final row is the candle still forming. Trading it means acting on
        # a price that can still move against the signal that produced it.
        return candles[:-1] if len(candles) > 1 else candles

    async def close(self) -> None:
        close = getattr(self._exchange, "close", None)
        if callable(close):
            try:
                await asyncio.to_thread(close)
            except Exception:  # pragma: no cover - best-effort teardown
                log.debug("exchange close failed", exc_info=True)
