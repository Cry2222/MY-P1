/**
 * Risk seam — the only component allowed to authorise an order.
 *
 * Every order passes through `assess`. There is no bypass path, and the engine
 * denies by default: if a limit cannot be evaluated, the order is rejected
 * rather than allowed through.
 *
 * Ported from the Python bot's `myp1/risk/engine.py`, decision for decision.
 */

import type { RiskSettings } from './config';
import type { Position, RiskDecision, Signal } from './models';

export interface RiskState {
  equity: number;
  realizedPnlToday: number;
  ordersToday: number;
  killed: boolean;
  paused: boolean;
}

export class RiskEngine {
  constructor(private readonly config: RiskSettings) {
    if (config.maxPositionNotional <= 0) throw new Error('maxPositionNotional must be > 0');
    if (config.riskFraction <= 0 || config.riskFraction > 1) {
      throw new Error('riskFraction must be in (0, 1]');
    }
    if (config.maxDailyLoss <= 0) throw new Error('maxDailyLoss must be > 0');
    if (config.maxOrdersPerDay <= 0) throw new Error('maxOrdersPerDay must be > 0');
  }

  /** Quantity to open with, capped by both the fraction and the notional. */
  sizeFor(equity: number, price: number): number {
    if (price <= 0) return 0;
    const budget = Math.min(equity * this.config.riskFraction, this.config.maxPositionNotional);
    return Math.max(budget / price, 0);
  }

  /**
   * Approve or deny the trade implied by `signal` given `position`.
   *
   * Exits are held to a narrower set of checks than entries: a limit must
   * never trap the bot in a position it is trying to leave.
   */
  assess(signal: Signal, position: Position, state: RiskState, isExit = false): RiskDecision {
    if (state.killed) {
      // The kill switch stops entries and exits alike. It exists so a human
      // can freeze the bot completely and unwind by hand.
      return { approved: false, quantity: 0, reason: 'kill switch engaged' };
    }

    if (isExit) {
      if (position.isFlat) {
        return { approved: false, quantity: 0, reason: 'already flat' };
      }
      return { approved: true, quantity: Math.abs(position.quantity), reason: 'exit approved' };
    }

    if (state.paused) {
      return { approved: false, quantity: 0, reason: 'trading paused' };
    }

    if (signal.target === 'flat') {
      return { approved: false, quantity: 0, reason: 'no exposure requested' };
    }

    if (state.realizedPnlToday <= -Math.abs(this.config.maxDailyLoss)) {
      return {
        approved: false,
        quantity: 0,
        reason: `daily loss limit hit (${state.realizedPnlToday.toFixed(2)} <= -${this.config.maxDailyLoss.toFixed(2)})`,
      };
    }

    if (state.ordersToday >= this.config.maxOrdersPerDay) {
      return {
        approved: false,
        quantity: 0,
        reason: `daily order cap hit (${state.ordersToday}/${this.config.maxOrdersPerDay})`,
      };
    }

    if (!position.isFlat) {
      return { approved: false, quantity: 0, reason: 'position already open' };
    }

    if (signal.price <= 0) {
      return { approved: false, quantity: 0, reason: 'invalid signal price' };
    }

    if (state.equity <= 0) {
      return { approved: false, quantity: 0, reason: 'no equity available' };
    }

    let quantity = this.sizeFor(state.equity, signal.price);
    let notional = quantity * signal.price;

    if (notional < this.config.minOrderNotional) {
      return {
        approved: false,
        quantity: 0,
        reason: `order too small (${notional.toFixed(2)} < ${this.config.minOrderNotional.toFixed(2)})`,
      };
    }

    if (notional > this.config.maxPositionNotional + 1e-9) {
      quantity = this.config.maxPositionNotional / signal.price;
      notional = quantity * signal.price;
    }

    if (notional > state.equity) {
      return { approved: false, quantity: 0, reason: 'order exceeds available equity' };
    }

    return { approved: true, quantity, reason: `approved ${notional.toFixed(2)} notional` };
  }
}
