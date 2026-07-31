/** BotSource backed by the engine running inside this app. */

import type { Candle } from '../engine/models';
import type { EngineStatus, TradingEngine } from '../engine/runner';
import type { BotSource, FillView } from './types';

export class LocalSource implements BotSource {
  readonly kind = 'local' as const;
  readonly label = 'This phone';

  constructor(private readonly engine: TradingEngine) {}

  async status(): Promise<EngineStatus> {
    return this.engine.status();
  }

  async fills(limit = 25): Promise<FillView[]> {
    const rows = await this.engine.getJournal().recentFills(limit);
    return rows.map((r) => ({
      id: r.id,
      side: r.side,
      quantity: r.quantity,
      price: r.price,
      realized: r.realized,
      timestamp: r.timestamp,
    }));
  }

  async candles(limit = 90): Promise<Candle[]> {
    return this.engine.candles(limit);
  }

  pause = () => this.engine.pause();
  resume = () => this.engine.resume();
  kill = () => this.engine.kill('user');
  revive = () => this.engine.revive();
  start = () => this.engine.start();
  stop = () => this.engine.stop();

  subscribe(listener: () => void): () => void {
    return this.engine.subscribe(listener);
  }
}
