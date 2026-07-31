"""Live venue backed by ccxt.

Constructing this class is the only point in the system where API credentials
enter memory. It refuses to build without an explicit `armed=True`, so an
accidental import or a mistyped config cannot open a path to real orders.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..core.models import Fill, Order, Side
from .base import ExecutionError

log = logging.getLogger(__name__)


class LiveVenue:
    def __init__(
        self,
        exchange_id: str,
        api_key: str,
        api_secret: str,
        *,
        armed: bool = False,
        timeout_ms: int = 20_000,
    ) -> None:
        if not armed:
            raise ExecutionError(
                "LiveVenue requires armed=True. Real orders are never the default."
            )
        if not (api_key and api_secret):
            raise ExecutionError("LiveVenue requires both api_key and api_secret")

        import ccxt

        if not hasattr(ccxt, exchange_id):
            raise ExecutionError(f"Unknown exchange {exchange_id!r}")

        self.name = f"live:{exchange_id}"
        self.is_live = True
        self._exchange = getattr(ccxt, exchange_id)({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": timeout_ms,
        })
        log.warning("LIVE venue armed on %s — orders will use real funds", exchange_id)

    async def submit(self, order: Order) -> Fill:
        if order.quantity <= 0:
            raise ExecutionError(f"non-positive quantity {order.quantity}")

        side = "buy" if order.side is Side.BUY else "sell"
        try:
            raw = await asyncio.to_thread(
                self._exchange.create_order,
                order.symbol, "market", side, order.quantity, None,
            )
        except Exception as exc:  # ccxt raises a wide family of errors
            raise ExecutionError(f"exchange rejected order: {exc}") from exc

        filled = float(raw.get("filled") or raw.get("amount") or order.quantity)
        price = float(raw.get("average") or raw.get("price") or order.price)
        fee_info = raw.get("fee") or {}
        fee = float(fee_info.get("cost") or 0.0)

        if filled <= 0:
            raise ExecutionError(f"exchange reported zero fill for {raw.get('id')}")

        return Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=filled,
            price=price,
            fee=fee,
            timestamp=int(raw.get("timestamp") or time.time() * 1000),
            venue=self.name,
            order_ref=str(raw.get("id") or order.client_id),
        )

    async def equity(self, mark_price: float) -> float:
        try:
            balance = await asyncio.to_thread(self._exchange.fetch_balance)
        except Exception as exc:
            raise ExecutionError(f"could not fetch balance: {exc}") from exc

        total = balance.get("total") or {}
        # Quote-currency cash plus any base inventory marked at the last price.
        quote = float(total.get("USDT") or total.get("USD") or 0.0)
        base_qty = sum(
            float(v or 0.0)
            for k, v in total.items()
            if k not in {"USDT", "USD"} and isinstance(v, (int, float))
        )
        return quote + base_qty * mark_price

    async def cancel_all(self, symbol: str) -> None:
        try:
            await asyncio.to_thread(self._exchange.cancel_all_orders, symbol)
        except Exception:  # pragma: no cover - venue dependent
            log.exception("cancel_all failed for %s", symbol)

    async def close(self) -> None:
        close = getattr(self._exchange, "close", None)
        if callable(close):
            try:
                await asyncio.to_thread(close)
            except Exception:  # pragma: no cover
                log.debug("exchange close failed", exc_info=True)
