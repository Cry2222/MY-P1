/**
 * Shapes returned by the MY-P1 control API.
 *
 * These mirror `myp1/api/server.py`. If a field changes there, it changes
 * here — that is the cost of the seam being HTTP rather than a shared import,
 * and it is deliberate: the bot must not depend on this app existing.
 */

export type Exposure = 'long' | 'flat' | 'short';
export type Mode = 'paper' | 'live';

export interface Status {
  mode: Mode;
  venue: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  running: boolean;
  killed: boolean;
  paused: boolean;
  ticks: number;
  errors: number;
  uptime_seconds: number;
  last_price: number;
  position_qty: number;
  position_side: Exposure;
  avg_price: number;
  unrealized: number;
  realized_today: number;
  realized_total: number;
  orders_today: number;
}

export interface PositionDetail {
  symbol: string;
  side: Exposure;
  quantity: number;
  avg_price: number;
  mark_price: number;
  unrealized: number;
  realized: number;
  is_flat: boolean;
}

export interface Pnl {
  realized_today: number;
  realized_total: number;
  unrealized: number;
  net: number;
  orders_today: number;
}

export interface FillRow {
  id: number;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  fee: number;
  venue: string;
  realized: number;
  timestamp: number;
  trade_date: string;
}

export interface Candle {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface CandleSeries {
  symbol: string;
  timeframe: string;
  candles: Candle[];
}

export interface ControlResult {
  ok: boolean;
  killed: boolean;
  paused: boolean;
  message: string;
}

export interface Health {
  ok: boolean;
  version: string;
  mode: Mode;
}

export interface Connection {
  baseUrl: string;
  token: string;
}
