/**
 * Market data seam.
 *
 * Public candle endpoints only, called with plain `fetch`. ccxt is not used
 * here on purpose: it needs Node core polyfills (crypto, stream, buffer) that
 * are a persistent source of breakage in React Native, and all of that machinery
 * exists to sign private requests. Reading public candles needs none of it.
 *
 * Each exchange gets a tiny adapter. Adding one is a URL and a row-shape.
 */

import type { Candle } from './models';

const TIMEOUT_MS = 15000;

export class MarketDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MarketDataError';
  }
}

export interface MarketDataSource {
  readonly name: string;
  fetchCandles(symbol: string, timeframe: string, limit: number): Promise<Candle[]>;
}

async function getJson(url: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new MarketDataError(`exchange returned ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (error instanceof MarketDataError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new MarketDataError('market data request timed out');
    }
    throw new MarketDataError('could not reach the exchange — check your connection');
  } finally {
    clearTimeout(timer);
  }
}

/** BTC/USDT -> BTCUSDT */
function compact(symbol: string): string {
  return symbol.replace('/', '').toUpperCase();
}

/** BTC/USDT -> BTC-USDT */
function dashed(symbol: string): string {
  return symbol.replace('/', '-').toUpperCase();
}

function row(symbol: string, t: unknown, o: unknown, h: unknown, l: unknown, c: unknown, v: unknown): Candle {
  return {
    symbol,
    timestamp: Number(t),
    open: Number(o),
    high: Number(h),
    low: Number(l),
    close: Number(c),
    volume: Number(v),
  };
}

/**
 * The final row from these endpoints is the candle still forming. Trading it
 * means acting on a price that can still move against the signal that produced
 * it, so it is dropped.
 */
function dropForming(candles: Candle[]): Candle[] {
  return candles.length > 1 ? candles.slice(0, -1) : candles;
}

class BinanceSource implements MarketDataSource {
  readonly name = 'binance';

  async fetchCandles(symbol: string, timeframe: string, limit: number): Promise<Candle[]> {
    const url =
      `https://api.binance.com/api/v3/klines?symbol=${compact(symbol)}` +
      `&interval=${timeframe}&limit=${Math.min(limit, 1000)}`;
    const data = await getJson(url);
    if (!Array.isArray(data)) throw new MarketDataError('unexpected response from Binance');
    const candles = data.map((r: any) => row(symbol, r[0], r[1], r[2], r[3], r[4], r[5]));
    return dropForming(candles);
  }
}

class BybitSource implements MarketDataSource {
  readonly name = 'bybit';

  private interval(timeframe: string): string {
    const map: Record<string, string> = {
      '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D',
    };
    const v = map[timeframe];
    if (!v) throw new MarketDataError(`Bybit does not support timeframe ${timeframe}`);
    return v;
  }

  async fetchCandles(symbol: string, timeframe: string, limit: number): Promise<Candle[]> {
    const url =
      `https://api.bybit.com/v5/market/kline?category=spot&symbol=${compact(symbol)}` +
      `&interval=${this.interval(timeframe)}&limit=${Math.min(limit, 1000)}`;
    const data: any = await getJson(url);
    const list = data?.result?.list;
    if (!Array.isArray(list)) {
      throw new MarketDataError(data?.retMsg || 'unexpected response from Bybit');
    }
    // Bybit returns newest first.
    const candles = list
      .map((r: any) => row(symbol, r[0], r[1], r[2], r[3], r[4], r[5]))
      .sort((a, b) => a.timestamp - b.timestamp);
    return dropForming(candles);
  }
}

class OkxSource implements MarketDataSource {
  readonly name = 'okx';

  private bar(timeframe: string): string {
    const map: Record<string, string> = {
      '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1H', '4h': '4H', '1d': '1D',
    };
    const v = map[timeframe];
    if (!v) throw new MarketDataError(`OKX does not support timeframe ${timeframe}`);
    return v;
  }

  async fetchCandles(symbol: string, timeframe: string, limit: number): Promise<Candle[]> {
    const url =
      `https://www.okx.com/api/v5/market/candles?instId=${dashed(symbol)}` +
      `&bar=${this.bar(timeframe)}&limit=${Math.min(limit, 300)}`;
    const data: any = await getJson(url);
    if (!Array.isArray(data?.data)) {
      throw new MarketDataError(data?.msg || 'unexpected response from OKX');
    }
    const candles = data.data
      .map((r: any) => row(symbol, r[0], r[1], r[2], r[3], r[4], r[5]))
      .sort((a: Candle, b: Candle) => a.timestamp - b.timestamp);
    return dropForming(candles);
  }
}

export function createMarketData(exchange: string): MarketDataSource {
  switch (exchange) {
    case 'binance':
      return new BinanceSource();
    case 'bybit':
      return new BybitSource();
    case 'okx':
      return new OkxSource();
    default:
      throw new MarketDataError(`unknown exchange ${exchange}`);
  }
}

/** Deterministic source for tests and for the built-in demo. */
export class ReplaySource implements MarketDataSource {
  readonly name = 'replay';
  private cursor: number;

  constructor(private readonly candles: Candle[], warmup = 1) {
    if (candles.length === 0) throw new Error('ReplaySource needs at least one candle');
    this.cursor = Math.min(warmup, candles.length);
  }

  get exhausted(): boolean {
    return this.cursor >= this.candles.length;
  }

  async fetchCandles(_symbol: string, _timeframe: string, limit: number): Promise<Candle[]> {
    if (!this.exhausted) this.cursor += 1;
    return this.candles.slice(0, this.cursor).slice(-limit);
  }
}
