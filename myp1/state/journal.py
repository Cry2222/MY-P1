"""Durable record of everything the bot did.

The journal is the source of truth for positions, PnL and control state. It is
written before any notification is sent, so a crash between execution and
Telegram can never lose a fill.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from ..core.models import Fill, Order, Position, Side, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS fills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL,
    quantity    REAL    NOT NULL,
    price       REAL    NOT NULL,
    fee         REAL    NOT NULL,
    venue       TEXT    NOT NULL,
    order_ref   TEXT,
    realized    REAL    NOT NULL DEFAULT 0,
    timestamp   INTEGER NOT NULL,
    trade_date  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fills_date ON fills(trade_date);
CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills(symbol);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL,
    quantity    REAL    NOT NULL,
    price       REAL    NOT NULL,
    reason      TEXT,
    status      TEXT    NOT NULL,
    detail      TEXT,
    timestamp   INTEGER NOT NULL,
    trade_date  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(trade_date);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    price       REAL    NOT NULL,
    reason      TEXT,
    timestamp   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS control (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  INTEGER NOT NULL
);
"""


def _trade_date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def today() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


class Journal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with closing(self._conn.cursor()) as cur:
            cur.executescript(SCHEMA)
        self._conn.commit()

    # -- writes ---------------------------------------------------------

    def record_signal(self, signal: Signal) -> None:
        self._conn.execute(
            "INSERT INTO signals (symbol, target, price, reason, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (signal.symbol, signal.target.value, signal.price, signal.reason, signal.timestamp),
        )
        self._conn.commit()

    def record_order(self, order: Order, status: str, detail: str = "") -> None:
        stamp = int(time.time() * 1000)
        self._conn.execute(
            "INSERT INTO orders (symbol, side, quantity, price, reason, status, detail, "
            "timestamp, trade_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.symbol, order.side.value, order.quantity, order.price,
                order.reason, status, detail, stamp, _trade_date(stamp),
            ),
        )
        self._conn.commit()

    def record_fill(self, fill: Fill, realized: float) -> None:
        self._conn.execute(
            "INSERT INTO fills (symbol, side, quantity, price, fee, venue, order_ref, "
            "realized, timestamp, trade_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fill.symbol, fill.side.value, fill.quantity, fill.price, fill.fee,
                fill.venue, fill.order_ref, realized, fill.timestamp,
                _trade_date(fill.timestamp),
            ),
        )
        self._conn.commit()

    # -- reads ----------------------------------------------------------

    def rebuild_position(self, symbol: str) -> Position:
        """Replay every fill for a symbol to recover the live position."""
        position = Position(symbol=symbol)
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE symbol = ? ORDER BY id ASC", (symbol,)
        ).fetchall()
        for row in rows:
            position.apply(
                Fill(
                    symbol=row["symbol"],
                    side=Side(row["side"]),
                    quantity=row["quantity"],
                    price=row["price"],
                    fee=row["fee"],
                    timestamp=row["timestamp"],
                    venue=row["venue"],
                    order_ref=row["order_ref"] or "",
                )
            )
        return position

    def realized_pnl(self, trade_date: str | None = None) -> float:
        if trade_date is None:
            row = self._conn.execute("SELECT COALESCE(SUM(realized), 0) AS v FROM fills").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(realized), 0) AS v FROM fills WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
        return float(row["v"])

    def order_count(self, trade_date: str | None = None) -> int:
        date = trade_date or today()
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE trade_date = ? AND status = 'filled'",
            (date,),
        ).fetchone()
        return int(row["n"])

    def recent_fills(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def fill_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"])

    # -- control state --------------------------------------------------

    def set_control(self, key: str, value: object) -> None:
        self._conn.execute(
            "INSERT INTO control (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value), int(time.time() * 1000)),
        )
        self._conn.commit()

    def get_control(self, key: str, default: object = None) -> object:
        row = self._conn.execute("SELECT value FROM control WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def close(self) -> None:
        self._conn.close()
