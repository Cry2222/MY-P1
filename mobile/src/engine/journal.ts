/**
 * Durable record of everything the engine did.
 *
 * The journal is the source of truth for position, PnL and control state. It
 * is written before any notification, so the app being killed between
 * executing and rendering can never lose a fill.
 *
 * Android kills backgrounded apps routinely, which makes this more load-bearing
 * here than on a server: every restart rebuilds the live position by replaying
 * fills rather than assuming flat.
 */

import * as SQLite from 'expo-sqlite';

import type { Fill, Order, Position, Side } from './models';
import { Position as PositionClass } from './models';

export interface FillRow {
  id: number;
  symbol: string;
  side: Side;
  quantity: number;
  price: number;
  fee: number;
  realized: number;
  timestamp: number;
  tradeDate: string;
}

const SCHEMA = `
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS fills (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol     TEXT    NOT NULL,
  side       TEXT    NOT NULL,
  quantity   REAL    NOT NULL,
  price      REAL    NOT NULL,
  fee        REAL    NOT NULL,
  venue      TEXT    NOT NULL,
  order_ref  TEXT,
  realized   REAL    NOT NULL DEFAULT 0,
  timestamp  INTEGER NOT NULL,
  trade_date TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fills_date ON fills(trade_date);

CREATE TABLE IF NOT EXISTS orders (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol     TEXT    NOT NULL,
  side       TEXT    NOT NULL,
  quantity   REAL    NOT NULL,
  price      REAL    NOT NULL,
  reason     TEXT,
  status     TEXT    NOT NULL,
  detail     TEXT,
  timestamp  INTEGER NOT NULL,
  trade_date TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(trade_date);

CREATE TABLE IF NOT EXISTS control (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  level      TEXT    NOT NULL,
  message    TEXT    NOT NULL,
  timestamp  INTEGER NOT NULL
);
`;

export function tradeDate(timestampMs: number): string {
  return new Date(timestampMs).toISOString().slice(0, 10);
}

export function today(): string {
  return tradeDate(Date.now());
}

export class Journal {
  private constructor(private readonly db: SQLite.SQLiteDatabase) {}

  static async open(name = 'myp1.db'): Promise<Journal> {
    const db = await SQLite.openDatabaseAsync(name);
    await db.execAsync(SCHEMA);
    return new Journal(db);
  }

  // -- writes ---------------------------------------------------------

  async recordFill(fill: Fill, realized: number): Promise<void> {
    await this.db.runAsync(
      `INSERT INTO fills (symbol, side, quantity, price, fee, venue, order_ref,
                          realized, timestamp, trade_date)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      fill.symbol, fill.side, fill.quantity, fill.price, fill.fee, fill.venue,
      fill.orderRef, realized, fill.timestamp, tradeDate(fill.timestamp),
    );
  }

  async recordOrder(order: Order, status: string, detail = ''): Promise<void> {
    const stamp = Date.now();
    await this.db.runAsync(
      `INSERT INTO orders (symbol, side, quantity, price, reason, status, detail,
                           timestamp, trade_date)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      order.symbol, order.side, order.quantity, order.price, order.reason,
      status, detail, stamp, tradeDate(stamp),
    );
  }

  async log(level: 'info' | 'warn' | 'error', message: string): Promise<void> {
    await this.db.runAsync(
      'INSERT INTO events (level, message, timestamp) VALUES (?, ?, ?)',
      level, message, Date.now(),
    );
  }

  // -- reads ----------------------------------------------------------

  /** Replay every fill for a symbol to recover the live position. */
  async rebuildPosition(symbol: string): Promise<Position> {
    const position = new PositionClass(symbol);
    const rows = await this.db.getAllAsync<any>(
      'SELECT * FROM fills WHERE symbol = ? ORDER BY id ASC',
      symbol,
    );
    for (const r of rows) {
      position.apply({
        symbol: r.symbol,
        side: r.side as Side,
        quantity: r.quantity,
        price: r.price,
        fee: r.fee,
        timestamp: r.timestamp,
        venue: r.venue,
        orderRef: r.order_ref ?? '',
      });
    }
    return position;
  }

  /** Cash a paper venue should hold, derived from every fill it made. */
  async rebuildCash(startingCash: number): Promise<number> {
    const rows = await this.db.getAllAsync<any>('SELECT * FROM fills ORDER BY id ASC');
    let cash = startingCash;
    for (const r of rows) {
      const notional = r.quantity * r.price;
      cash += (r.side === 'buy' ? -notional : notional) - r.fee;
    }
    return cash;
  }

  async realizedPnl(date?: string): Promise<number> {
    const row = date
      ? await this.db.getFirstAsync<any>(
          'SELECT COALESCE(SUM(realized), 0) AS v FROM fills WHERE trade_date = ?', date)
      : await this.db.getFirstAsync<any>('SELECT COALESCE(SUM(realized), 0) AS v FROM fills');
    return Number(row?.v ?? 0);
  }

  async orderCount(date: string): Promise<number> {
    const row = await this.db.getFirstAsync<any>(
      "SELECT COUNT(*) AS n FROM orders WHERE trade_date = ? AND status = 'filled'",
      date,
    );
    return Number(row?.n ?? 0);
  }

  async recentFills(limit = 25): Promise<FillRow[]> {
    const rows = await this.db.getAllAsync<any>(
      'SELECT * FROM fills ORDER BY id DESC LIMIT ?', limit,
    );
    return rows.map((r) => ({
      id: r.id,
      symbol: r.symbol,
      side: r.side as Side,
      quantity: r.quantity,
      price: r.price,
      fee: r.fee,
      realized: r.realized,
      timestamp: r.timestamp,
      tradeDate: r.trade_date,
    }));
  }

  async fillCount(): Promise<number> {
    const row = await this.db.getFirstAsync<any>('SELECT COUNT(*) AS n FROM fills');
    return Number(row?.n ?? 0);
  }

  async recentEvents(limit = 50): Promise<{ level: string; message: string; timestamp: number }[]> {
    return this.db.getAllAsync<any>(
      'SELECT level, message, timestamp FROM events ORDER BY id DESC LIMIT ?', limit,
    );
  }

  // -- control state --------------------------------------------------

  async setControl(key: string, value: unknown): Promise<void> {
    await this.db.runAsync(
      `INSERT INTO control (key, value, updated_at) VALUES (?, ?, ?)
       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
      key, JSON.stringify(value), Date.now(),
    );
  }

  async getControl<T>(key: string, fallback: T): Promise<T> {
    const row = await this.db.getFirstAsync<any>('SELECT value FROM control WHERE key = ?', key);
    if (!row) return fallback;
    try {
      return JSON.parse(row.value) as T;
    } catch {
      return fallback;
    }
  }

  /** Wipe trading history. Control state (including the kill switch) survives. */
  async reset(): Promise<void> {
    await this.db.execAsync('DELETE FROM fills; DELETE FROM orders; DELETE FROM events;');
  }
}
