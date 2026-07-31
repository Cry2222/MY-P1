/**
 * Domain types for the in-app trading engine.
 *
 * A direct port of the Python bot's `myp1/core/models.py`, deliberately kept
 * shape-for-shape identical. The two implementations trade the same way, and
 * keeping the types aligned is what makes that checkable rather than hoped for.
 */

export type Side = 'buy' | 'sell';

/**
 * Target market exposure a strategy wants to hold.
 *
 * Strategies declare the position they want, not the trade to get there. The
 * runner diffs the target against the live position and derives the order, so
 * a strategy that repeats the same signal cannot double-enter.
 */
export type Exposure = 'long' | 'flat' | 'short';

export interface Candle {
  symbol: string;
  timestamp: number; // ms since epoch, candle open time
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Signal {
  symbol: string;
  target: Exposure;
  price: number;
  timestamp: number;
  reason: string;
  confidence: number;
}

export interface Order {
  symbol: string;
  side: Side;
  quantity: number;
  price: number;
  reason: string;
  clientId: string;
}

export interface Fill {
  symbol: string;
  side: Side;
  quantity: number;
  price: number;
  fee: number;
  timestamp: number;
  venue: string;
  orderRef: string;
}

export interface RiskDecision {
  approved: boolean;
  quantity: number;
  reason: string;
}

export class Position {
  quantity = 0; // signed: positive long, negative short
  avgPrice = 0;
  realizedPnl = 0;

  constructor(readonly symbol: string) {}

  get exposure(): Exposure {
    if (this.quantity > 0) return 'long';
    if (this.quantity < 0) return 'short';
    return 'flat';
  }

  get isFlat(): boolean {
    return this.quantity === 0;
  }

  unrealizedPnl(mark: number): number {
    if (this.isFlat) return 0;
    return (mark - this.avgPrice) * this.quantity;
  }

  /** Fold a fill into this position, returning the realized PnL from it. */
  apply(fill: Fill): number {
    const signed = fill.side === 'buy' ? fill.quantity : -fill.quantity;
    let realized = 0;

    if (this.quantity === 0 || this.quantity > 0 === signed > 0) {
      // Opening or adding: weighted-average the entry price.
      const total = this.quantity + signed;
      if (total !== 0) {
        this.avgPrice = (this.avgPrice * this.quantity + fill.price * signed) / total;
      }
      this.quantity = total;
    } else {
      // Reducing, closing, or flipping.
      const closing = Math.min(Math.abs(signed), Math.abs(this.quantity));
      const direction = this.quantity > 0 ? 1 : -1;
      realized = (fill.price - this.avgPrice) * closing * direction;
      this.quantity += signed;
      if (this.quantity === 0) {
        this.avgPrice = 0;
      } else if (this.quantity > 0 !== direction > 0) {
        // Flipped through zero; the remainder opens at the fill price.
        this.avgPrice = fill.price;
      }
    }

    realized -= fill.fee;
    this.realizedPnl += realized;
    return realized;
  }

  static restore(symbol: string, quantity: number, avgPrice: number, realizedPnl: number): Position {
    const p = new Position(symbol);
    p.quantity = quantity;
    p.avgPrice = avgPrice;
    p.realizedPnl = realizedPnl;
    return p;
  }
}

export function newClientId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
}
