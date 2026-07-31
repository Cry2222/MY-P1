"""Simulated venue.

Fills at the reference price degraded by slippage, with fees applied, so paper
results are pessimistic rather than flattering. Balances live in memory and
are rebuilt from the journal on restart by the runner.
"""

from __future__ import annotations

import logging
import time

from ..core.models import Fill, Order, Side
from .base import ExecutionError

log = logging.getLogger(__name__)


class PaperVenue:
    def __init__(
        self,
        starting_cash: float = 1000.0,
        *,
        fee_pct: float = 0.1,
        slippage_pct: float = 0.02,
        allow_short: bool = False,
    ) -> None:
        self.name = "paper"
        self.is_live = False
        self.cash = starting_cash
        self.starting_cash = starting_cash
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.allow_short = allow_short
        self._inventory: dict[str, float] = {}

    def _fill_price(self, order: Order) -> float:
        # Slippage always works against the order.
        drift = order.price * (self.slippage_pct / 100)
        return order.price + drift if order.side is Side.BUY else order.price - drift

    async def submit(self, order: Order) -> Fill:
        if order.quantity <= 0:
            raise ExecutionError(f"non-positive quantity {order.quantity}")

        price = self._fill_price(order)
        if price <= 0:
            raise ExecutionError(f"non-positive fill price {price}")

        notional = price * order.quantity
        fee = notional * (self.fee_pct / 100)

        if order.side is Side.BUY:
            if notional + fee > self.cash + 1e-9:
                raise ExecutionError(
                    f"insufficient paper cash: need {notional + fee:.2f}, have {self.cash:.2f}"
                )
            self.cash -= notional + fee
            self._inventory[order.symbol] = self._inventory.get(order.symbol, 0.0) + order.quantity
        else:
            held = self._inventory.get(order.symbol, 0.0)
            if not self.allow_short and order.quantity > held + 1e-9:
                raise ExecutionError(
                    f"insufficient paper inventory: need {order.quantity}, have {held}"
                )
            self.cash += notional - fee
            self._inventory[order.symbol] = held - order.quantity

        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee=fee,
            timestamp=int(time.time() * 1000),
            venue=self.name,
            order_ref=order.client_id,
        )
        log.info("paper fill %s %s %.8f @ %.4f (fee %.4f)",
                 fill.side.value, fill.symbol, fill.quantity, fill.price, fill.fee)
        return fill

    async def equity(self, mark_price: float) -> float:
        holdings = sum(qty * mark_price for qty in self._inventory.values())
        return self.cash + holdings

    def inventory(self, symbol: str) -> float:
        return self._inventory.get(symbol, 0.0)

    def seed_inventory(self, symbol: str, quantity: float, cash: float) -> None:
        """Restore simulator state after a restart, from journalled fills."""
        self._inventory[symbol] = quantity
        self.cash = cash

    async def close(self) -> None:
        return None
