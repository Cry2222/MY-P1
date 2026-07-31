/**
 * BotSource backed by a Python bot's HTTP control API.
 *
 * Kept because the seam costs almost nothing and the choice is real: a bot on
 * a server survives a dead battery, which the on-phone engine cannot.
 */

import { api } from '../api/client';
import type { Connection } from '../api/types';
import type { Candle } from '../engine/models';
import type { EngineStatus } from '../engine/runner';
import type { BotSource, FillView } from './types';

export class RemoteSource implements BotSource {
  readonly kind = 'remote' as const;
  readonly label: string;

  constructor(private readonly connection: Connection) {
    this.label = connection.baseUrl.replace(/^https?:\/\//, '');
  }

  async status(): Promise<EngineStatus> {
    const s = await api.status(this.connection);
    // The Python bot reports snake_case; map it onto the same shape the
    // dashboard already reads so the screen needs no special cases.
    return {
      running: s.running,
      killed: s.killed,
      paused: s.paused,
      mode: 'paper',
      venue: s.venue,
      exchange: s.venue,
      symbol: s.symbol,
      timeframe: s.timeframe,
      strategy: s.strategy,
      ticks: s.ticks,
      errors: s.errors,
      startedAt: Date.now() - s.uptime_seconds * 1000,
      lastTickAt: Date.now(),
      lastPrice: s.last_price,
      positionSide: s.position_side,
      positionQty: s.position_qty,
      avgPrice: s.avg_price,
      unrealized: s.unrealized,
      realizedToday: s.realized_today,
      realizedTotal: s.realized_total,
      ordersToday: s.orders_today,
      equity: 0,
      lastError: '',
    };
  }

  async fills(limit = 25): Promise<FillView[]> {
    const body = await api.fills(this.connection, limit);
    return body.fills.map((f) => ({
      id: f.id,
      side: f.side,
      quantity: f.quantity,
      price: f.price,
      realized: f.realized,
      timestamp: f.timestamp,
    }));
  }

  async candles(limit = 90): Promise<Candle[]> {
    const body = await api.candles(this.connection, limit);
    return body.candles.map((c) => ({
      symbol: body.symbol,
      timestamp: c.t,
      open: c.o,
      high: c.h,
      low: c.l,
      close: c.c,
      volume: c.v,
    }));
  }

  pause = async () => void (await api.pause(this.connection));
  resume = async () => void (await api.resume(this.connection));
  kill = async () => void (await api.kill(this.connection));
  revive = async () => void (await api.revive(this.connection));
}
