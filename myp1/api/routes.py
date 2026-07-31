"""Route logic, shared by both API servers.

There are two HTTP servers — FastAPI for a desktop or a server, and a
stdlib-only one for phones where compiled dependencies cannot be installed.
Both are thin transports over the functions here, so the contract cannot
drift between them: a behaviour change lands in one place and the contract
tests run against both.

Nothing in this module imports a web framework.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner import TradingRunner

log = logging.getLogger(__name__)

FILLS_MIN, FILLS_MAX = 1, 200
CANDLES_MIN, CANDLES_MAX = 10, 500

CONTROL_ACTIONS = ("pause", "resume", "kill", "revive")


class ApiFault(Exception):
    """A response that is not 200, carrying the status and the detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def parse_limit(raw: str | int | None, default: int, low: int, high: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiFault(422, f"limit must be an integer between {low} and {high}") from exc
    if not low <= value <= high:
        raise ApiFault(422, f"limit must be between {low} and {high}")
    return value


def health(runner: TradingRunner) -> dict[str, Any]:
    """Liveness only. Deliberately leaks nothing about the account."""
    from .. import __version__

    return {
        "ok": True,
        "version": __version__,
        "mode": "live" if runner.config.is_live else "paper",
    }


def status(runner: TradingRunner) -> dict[str, Any]:
    return runner.status()


def position(runner: TradingRunner) -> dict[str, Any]:
    p = runner.position
    return {
        "symbol": p.symbol,
        "side": p.exposure.value,
        "quantity": p.quantity,
        "avg_price": p.avg_price,
        "mark_price": runner.last_price,
        "unrealized": p.unrealized_pnl(runner.last_price),
        "realized": p.realized_pnl,
        "is_flat": p.is_flat,
    }


def pnl(runner: TradingRunner) -> dict[str, Any]:
    s = runner.status()
    return {
        "realized_today": s["realized_today"],
        "realized_total": s["realized_total"],
        "unrealized": s["unrealized"],
        "net": s["realized_total"] + s["unrealized"],
        "orders_today": s["orders_today"],
    }


def fills(runner: TradingRunner, limit: str | int | None = None) -> dict[str, Any]:
    count = parse_limit(limit, 25, FILLS_MIN, FILLS_MAX)
    return {"fills": runner.journal.recent_fills(limit=count)}


async def candles(runner: TradingRunner, limit: str | int | None = None) -> dict[str, Any]:
    count = parse_limit(limit, 100, CANDLES_MIN, CANDLES_MAX)
    try:
        rows = await runner.market_data.fetch_candles(
            runner.symbol, runner.config.timeframe, limit=count
        )
    except Exception as exc:
        log.warning("candle fetch failed for API: %s", exc)
        raise ApiFault(503, "market data unavailable") from exc
    return {
        "symbol": runner.symbol,
        "timeframe": runner.config.timeframe,
        "candles": [
            {"t": c.timestamp, "o": c.open, "h": c.high,
             "l": c.low, "c": c.close, "v": c.volume}
            for c in rows
        ],
    }


def control(runner: TradingRunner, action: str) -> dict[str, Any]:
    if action not in CONTROL_ACTIONS:
        raise ApiFault(404, f"unknown control action {action!r}")

    if action == "pause":
        runner.pause()
        message = "Paused. Open positions can still exit."
    elif action == "resume":
        if runner.killed:
            raise ApiFault(409, "kill switch is engaged; revive first")
        runner.resume()
        message = "Resumed."
    elif action == "kill":
        runner.kill("api")
        message = "Kill switch engaged. No orders will be placed, including exits."
    else:
        runner.revive()
        message = "Kill switch released."

    return {
        "ok": True,
        "killed": runner.killed,
        "paused": runner.paused,
        "message": message,
    }
