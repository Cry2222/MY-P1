/**
 * Execution seam.
 *
 * Only a paper venue exists on-device. Live trading needs HMAC request signing
 * with an exchange secret held on the phone, which is a materially different
 * risk decision from simulating fills — it is deliberately not smuggled in
 * behind a settings toggle.
 */

import type { Fill, Order } from './models';

export class ExecutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExecutionError';
  }
}

export interface ExecutionVenue {
  readonly name: string;
  readonly isLive: boolean;
  submit(order: Order): Promise<Fill>;
  equity(markPrice: number): number;
}

/**
 * Simulated venue.
 *
 * Fills at the reference price degraded by slippage, with fees applied, so
 * paper results are pessimistic rather than flattering.
 */
export class PaperVenue implements ExecutionVenue {
  readonly name = 'paper';
  readonly isLive = false;

  cash: number;
  private inventory: Record<string, number> = {};

  constructor(
    readonly startingCash: number,
    private readonly feePct: number,
    private readonly slippagePct: number,
  ) {
    this.cash = startingCash;
  }

  private fillPrice(order: Order): number {
    // Slippage always works against the order.
    const drift = order.price * (this.slippagePct / 100);
    return order.side === 'buy' ? order.price + drift : order.price - drift;
  }

  async submit(order: Order): Promise<Fill> {
    if (order.quantity <= 0) {
      throw new ExecutionError(`non-positive quantity ${order.quantity}`);
    }

    const price = this.fillPrice(order);
    if (price <= 0) {
      throw new ExecutionError(`non-positive fill price ${price}`);
    }

    const notional = price * order.quantity;
    const fee = notional * (this.feePct / 100);

    if (order.side === 'buy') {
      if (notional + fee > this.cash + 1e-9) {
        throw new ExecutionError(
          `insufficient paper cash: need ${(notional + fee).toFixed(2)}, have ${this.cash.toFixed(2)}`,
        );
      }
      this.cash -= notional + fee;
      this.inventory[order.symbol] = (this.inventory[order.symbol] ?? 0) + order.quantity;
    } else {
      const held = this.inventory[order.symbol] ?? 0;
      if (order.quantity > held + 1e-9) {
        throw new ExecutionError(
          `insufficient paper inventory: need ${order.quantity}, have ${held}`,
        );
      }
      this.cash += notional - fee;
      this.inventory[order.symbol] = held - order.quantity;
    }

    return {
      symbol: order.symbol,
      side: order.side,
      quantity: order.quantity,
      price,
      fee,
      timestamp: Date.now(),
      venue: this.name,
      orderRef: order.clientId,
    };
  }

  equity(markPrice: number): number {
    const holdings = Object.values(this.inventory).reduce((sum, q) => sum + q * markPrice, 0);
    return this.cash + holdings;
  }

  held(symbol: string): number {
    return this.inventory[symbol] ?? 0;
  }

  /** Restore simulator state after an app restart, from journalled fills. */
  seed(symbol: string, quantity: number, cash: number): void {
    this.inventory[symbol] = quantity;
    this.cash = cash;
  }
}
