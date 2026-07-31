"""Execution seam.

Paper and live venues are interchangeable behind this protocol. The runner
holds one of them and cannot tell which, which is what makes "run the exact
same strategy against a simulator first" a configuration change rather than a
code change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.models import Fill, Order


@runtime_checkable
class ExecutionVenue(Protocol):
    name: str
    is_live: bool

    async def submit(self, order: Order) -> Fill:
        """Execute the order, returning the resulting fill.

        Raises ExecutionError if the order could not be filled.
        """
        ...

    async def equity(self, mark_price: float) -> float:
        """Current account equity in quote currency."""
        ...

    async def close(self) -> None:
        ...


class ExecutionError(RuntimeError):
    """Raised when a venue could not execute an order."""
