/**
 * Strategy seam.
 *
 * A strategy is a pure function of candle history to a desired exposure. It
 * never places orders, never reads account state, and never touches the UI.
 */

import type { Candle, Exposure, Signal } from './models';
import { ema } from './indicators';

export interface Strategy {
  readonly name: string;
  readonly warmup: number;
  evaluate(candles: Candle[]): Signal | null;
}

export class EmaCrossStrategy implements Strategy {
  readonly name: string;

  constructor(
    private readonly fastPeriod: number,
    private readonly slowPeriod: number,
    private readonly longOnly = true,
  ) {
    if (fastPeriod >= slowPeriod) {
      throw new Error('fastPeriod must be less than slowPeriod');
    }
    this.name = `ema_cross(${fastPeriod},${slowPeriod})`;
  }

  get warmup(): number {
    // Slow EMA needs `slowPeriod` bars to seed, plus one to have a prior value
    // to compare against for a crossover.
    return this.slowPeriod + 1;
  }

  evaluate(candles: Candle[]): Signal | null {
    if (candles.length < this.warmup) return null;

    const closes = candles.map((c) => c.close);
    const fast = ema(closes, this.fastPeriod);
    const slow = ema(closes, this.slowPeriod);
    if (fast.length < 2 || slow.length < 2) return null;

    const fastNow = fast[fast.length - 1];
    const fastPrev = fast[fast.length - 2];
    const slowNow = slow[slow.length - 1];
    const slowPrev = slow[slow.length - 2];

    const last = candles[candles.length - 1];
    const spread = fastNow - slowNow;
    const prevSpread = fastPrev - slowPrev;

    let target: Exposure;
    if (spread > 0) target = 'long';
    else if (this.longOnly) target = 'flat';
    else target = 'short';

    const crossed = spread > 0 !== prevSpread > 0;
    const confidence = last.close
      ? Math.min(1, (Math.abs(spread) / last.close) * 100)
      : 0;

    return {
      symbol: last.symbol,
      target,
      price: last.close,
      timestamp: last.timestamp,
      reason: `fast=${fastNow.toFixed(4)} slow=${slowNow.toFixed(4)} ${
        crossed ? 'crossover' : 'trend'
      }`,
      confidence,
    };
  }
}
