/**
 * Tests for the in-app engine's pure logic.
 *
 * These run off-device with `node --test` (see `npm run test`). They cover the
 * parts that decide how money moves — position accounting, indicators, the
 * strategy, and the risk gate — and they mirror the Python suite's cases so
 * the two implementations can be compared directly rather than assumed equal.
 *
 * Anything touching SQLite or fetch is not covered here; that needs a device.
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { validateSettings, DEFAULT_SETTINGS, type EngineSettings } from './config';
import { ema, sma } from './indicators';
import { Position, type Fill, type Side, type Signal } from './models';
import { RiskEngine, type RiskState } from './risk';
import { EmaCrossStrategy } from './strategy';
import { PaperVenue, ExecutionError } from './venue';

const SYMBOL = 'TEST/USDT';

function fill(side: Side, quantity: number, price: number, fee = 0): Fill {
  return { symbol: SYMBOL, side, quantity, price, fee, timestamp: 0, venue: 'test', orderRef: '' };
}

function candles(closes: number[]) {
  return closes.map((close, i) => ({
    symbol: SYMBOL,
    timestamp: i * 60_000,
    open: close,
    high: close * 1.001,
    low: close * 0.999,
    close,
    volume: 1,
  }));
}

const ramp = (n: number, start: number, step: number) =>
  Array.from({ length: n }, (_, i) => start + i * step);

function signal(target: 'long' | 'flat' | 'short' = 'long', price = 100): Signal {
  return { symbol: SYMBOL, target, price, timestamp: 0, reason: '', confidence: 1 };
}

function state(overrides: Partial<RiskState> = {}): RiskState {
  return {
    equity: 1000, realizedPnlToday: 0, ordersToday: 0,
    killed: false, paused: false, ...overrides,
  };
}

const RISK = { ...DEFAULT_SETTINGS.risk, riskFraction: 0.1 };

function longPosition(qty = 1, price = 100): Position {
  const p = new Position(SYMBOL);
  p.apply(fill('buy', qty, price));
  return p;
}

// -- indicators ---------------------------------------------------------

describe('indicators', () => {
  it('sma matches a manual average', () => {
    assert.deepEqual(sma([1, 2, 3, 4, 5], 3), [2, 3, 4]);
  });

  it('sma is empty when the series is too short', () => {
    assert.deepEqual(sma([1, 2], 5), []);
  });

  it('ema seeds on the simple average', () => {
    const out = ema([1, 2, 3, 4, 5, 6], 3);
    assert.equal(out[0], 2);
    assert.equal(out.length, 4);
  });

  it('ema tracks a constant series exactly', () => {
    assert.deepEqual(ema(Array(20).fill(7), 5), Array(16).fill(7));
  });

  it('ema reacts faster than sma one bar after a step', () => {
    const values = [...Array(10).fill(10), 20];
    assert.ok(ema(values, 5).at(-1)! > sma(values, 5).at(-1)!);
  });

  it('rejects a non-positive period', () => {
    assert.throws(() => ema([1, 2, 3], 0));
  });
});

// -- position accounting ------------------------------------------------

describe('position', () => {
  it('opening a long sets the average price', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 2, 100));
    assert.equal(p.quantity, 2);
    assert.equal(p.avgPrice, 100);
    assert.equal(p.exposure, 'long');
  });

  it('adding to a long averages the entry', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 1, 100));
    p.apply(fill('buy', 1, 200));
    assert.equal(p.avgPrice, 150);
  });

  it('closing a long realizes the gain', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 2, 100));
    assert.equal(p.apply(fill('sell', 2, 110)), 20);
    assert.ok(p.isFlat);
    assert.equal(p.avgPrice, 0);
  });

  it('fees reduce realized pnl on both sides', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 1, 100, 0.5));
    assert.equal(p.apply(fill('sell', 1, 110, 0.5)), 9.5);
    assert.equal(p.realizedPnl, 9);
  });

  it('a partial close keeps the remainder at entry price', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 4, 100));
    assert.equal(p.apply(fill('sell', 1, 120)), 20);
    assert.equal(p.quantity, 3);
    assert.equal(p.avgPrice, 100);
  });

  it('a short profits when price falls', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('sell', 2, 100));
    assert.equal(p.exposure, 'short');
    assert.equal(p.apply(fill('buy', 2, 90)), 20);
  });

  it('flipping through zero reprices the new side', () => {
    const p = new Position(SYMBOL);
    p.apply(fill('buy', 1, 100));
    assert.equal(p.apply(fill('sell', 3, 110)), 10);
    assert.equal(p.quantity, -2);
    assert.equal(p.avgPrice, 110);
  });

  it('marks unrealized against the current price', () => {
    const p = longPosition(2, 100);
    assert.equal(p.unrealizedPnl(105), 10);
    assert.equal(p.unrealizedPnl(95), -10);
  });

  it('a flat book has no unrealized pnl', () => {
    assert.equal(new Position(SYMBOL).unrealizedPnl(1234), 0);
  });
});

// -- strategy -----------------------------------------------------------

describe('strategy', () => {
  it('abstains before warmup', () => {
    assert.equal(new EmaCrossStrategy(3, 8).evaluate(candles(ramp(5, 100, 1))), null);
  });

  it('goes long in a rising market', () => {
    assert.equal(new EmaCrossStrategy(3, 8).evaluate(candles(ramp(40, 100, 1)))!.target, 'long');
  });

  it('goes flat in a falling market when long only', () => {
    assert.equal(new EmaCrossStrategy(3, 8).evaluate(candles(ramp(40, 200, -1)))!.target, 'flat');
  });

  it('goes short in a falling market when shorting is enabled', () => {
    assert.equal(
      new EmaCrossStrategy(3, 8, false).evaluate(candles(ramp(40, 200, -1)))!.target, 'short');
  });

  it('reports the last close as the signal price', () => {
    const series = candles(ramp(40, 100, 1));
    assert.equal(new EmaCrossStrategy(3, 8).evaluate(series)!.price, series.at(-1)!.close);
  });

  it('keeps confidence bounded', () => {
    const s = new EmaCrossStrategy(3, 8).evaluate(candles(ramp(60, 100, 5)))!;
    assert.ok(s.confidence >= 0 && s.confidence <= 1);
  });

  it('rejects inverted periods', () => {
    assert.throws(() => new EmaCrossStrategy(20, 10));
  });
});

// -- risk ---------------------------------------------------------------

describe('risk', () => {
  it('approves a clean entry and sizes it', () => {
    const d = new RiskEngine(RISK).assess(signal(), new Position(SYMBOL), state());
    assert.ok(d.approved);
    assert.equal(d.quantity, 1); // 10% of 1000 equity / price 100
  });

  it('caps the position by max notional', () => {
    const d = new RiskEngine(RISK).assess(signal(), new Position(SYMBOL), state({ equity: 100_000 }));
    assert.ok(Math.abs(d.quantity * 100 - RISK.maxPositionNotional) < 1e-9);
  });

  it('the kill switch blocks entries', () => {
    const d = new RiskEngine(RISK).assess(signal(), new Position(SYMBOL), state({ killed: true }));
    assert.equal(d.approved, false);
    assert.match(d.reason, /kill switch/);
  });

  it('the kill switch also blocks exits', () => {
    // A kill switch that let exits through would not be a full stop.
    const d = new RiskEngine(RISK).assess(
      signal('flat'), longPosition(), state({ killed: true }), true);
    assert.equal(d.approved, false);
  });

  it('pause blocks entries but not exits', () => {
    const engine = new RiskEngine(RISK);
    assert.equal(engine.assess(signal(), new Position(SYMBOL), state({ paused: true })).approved, false);

    const exit = engine.assess(signal('flat'), longPosition(), state({ paused: true }), true);
    assert.ok(exit.approved);
    assert.equal(exit.quantity, 1);
  });

  it('the daily loss limit halts new entries', () => {
    const d = new RiskEngine(RISK).assess(
      signal(), new Position(SYMBOL), state({ realizedPnlToday: -25 }));
    assert.equal(d.approved, false);
    assert.match(d.reason, /daily loss limit/);
  });

  it('the daily loss limit still allows an exit', () => {
    const d = new RiskEngine(RISK).assess(
      signal('flat'), longPosition(), state({ realizedPnlToday: -100 }), true);
    assert.ok(d.approved);
  });

  it('the daily order cap stops a runaway loop', () => {
    const d = new RiskEngine(RISK).assess(
      signal(), new Position(SYMBOL), state({ ordersToday: 40 }));
    assert.equal(d.approved, false);
    assert.match(d.reason, /order cap/);
  });

  it('does not stack a second position', () => {
    const d = new RiskEngine(RISK).assess(signal(), longPosition(), state());
    assert.equal(d.approved, false);
    assert.match(d.reason, /already open/);
  });

  it('rejects dust orders', () => {
    const d = new RiskEngine(RISK).assess(signal(), new Position(SYMBOL), state({ equity: 10 }));
    assert.equal(d.approved, false);
    assert.match(d.reason, /too small/);
  });

  it('rejects when equity is unknown', () => {
    const d = new RiskEngine(RISK).assess(signal(), new Position(SYMBOL), state({ equity: 0 }));
    assert.equal(d.approved, false);
  });

  it('rejects an invalid price', () => {
    const d = new RiskEngine(RISK).assess(signal('long', 0), new Position(SYMBOL), state());
    assert.equal(d.approved, false);
  });

  it('refuses an exit on a flat book', () => {
    const d = new RiskEngine(RISK).assess(signal('flat'), new Position(SYMBOL), state(), true);
    assert.equal(d.approved, false);
    assert.match(d.reason, /already flat/);
  });

  it('cannot be constructed with a disabled limit', () => {
    assert.throws(() => new RiskEngine({ ...RISK, maxDailyLoss: 0 }));
    assert.throws(() => new RiskEngine({ ...RISK, riskFraction: 1.5 }));
    assert.throws(() => new RiskEngine({ ...RISK, maxOrdersPerDay: 0 }));
  });
});

// -- paper venue --------------------------------------------------------

describe('paper venue', () => {
  const order = (side: Side, quantity: number, price = 100) => ({
    symbol: SYMBOL, side, quantity, price, reason: '', clientId: 'test',
  });

  it('a buy debits cash and credits inventory', async () => {
    const v = new PaperVenue(1000, 0, 0);
    await v.submit(order('buy', 2));
    assert.equal(v.cash, 800);
    assert.equal(v.held(SYMBOL), 2);
  });

  it('slippage always works against the order', async () => {
    const v = new PaperVenue(1000, 0, 1);
    assert.equal((await v.submit(order('buy', 1))).price, 101);
    assert.equal((await v.submit(order('sell', 1))).price, 99);
  });

  it('charges fees', async () => {
    const v = new PaperVenue(1000, 1, 0);
    assert.equal((await v.submit(order('buy', 1))).fee, 1);
    assert.equal(v.cash, 899);
  });

  it('cannot spend more cash than the account holds', async () => {
    const v = new PaperVenue(50, 0, 0);
    await assert.rejects(() => v.submit(order('buy', 10)), ExecutionError);
  });

  it('cannot sell what is not held', async () => {
    const v = new PaperVenue(1000, 0, 0);
    await assert.rejects(() => v.submit(order('sell', 1)), ExecutionError);
  });

  it('rejects a non-positive quantity', async () => {
    const v = new PaperVenue(1000, 0, 0);
    await assert.rejects(() => v.submit(order('buy', 0)), ExecutionError);
  });

  it('marks inventory at the current price', async () => {
    const v = new PaperVenue(1000, 0, 0);
    await v.submit(order('buy', 5));
    assert.equal(v.equity(100), 1000);
    assert.equal(v.equity(120), 1100);
  });

  it('a profitable round trip grows cash', async () => {
    const v = new PaperVenue(1000, 0, 0);
    await v.submit(order('buy', 1, 100));
    await v.submit(order('sell', 1, 110));
    assert.equal(Math.round(v.cash), 1010);
    assert.equal(v.held(SYMBOL), 0);
  });
});

// -- settings validation ------------------------------------------------

describe('settings', () => {
  const bad = (patch: Partial<EngineSettings>) =>
    validateSettings({ ...DEFAULT_SETTINGS, ...patch } as EngineSettings);

  it('accepts the defaults', () => {
    assert.deepEqual(validateSettings(DEFAULT_SETTINGS), []);
  });

  it('rejects inverted ema periods', () => {
    assert.ok(bad({ fastPeriod: 50, slowPeriod: 10 }).length > 0);
  });

  it('rejects a malformed symbol', () => {
    assert.ok(bad({ symbol: 'BTCUSDT' }).length > 0);
    assert.deepEqual(bad({ symbol: 'eth/usdt' }), []);
  });

  it('rejects a too-fast poll interval', () => {
    assert.ok(bad({ pollSeconds: 1 }).length > 0);
  });

  it('refuses to disable a risk limit', () => {
    assert.ok(bad({ risk: { ...DEFAULT_SETTINGS.risk, maxDailyLoss: 0 } }).length > 0);
    assert.ok(bad({ risk: { ...DEFAULT_SETTINGS.risk, maxPositionNotional: 0 } }).length > 0);
    assert.ok(bad({ risk: { ...DEFAULT_SETTINGS.risk, maxOrdersPerDay: 0 } }).length > 0);
    assert.ok(bad({ risk: { ...DEFAULT_SETTINGS.risk, riskFraction: 2 } }).length > 0);
  });
});
