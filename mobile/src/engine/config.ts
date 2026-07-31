/**
 * Engine settings.
 *
 * On the Python side these come from environment variables. Here they come
 * from a settings screen and are persisted, but the shape and the limits are
 * the same — including the rule that risk limits cannot be switched off.
 */

export type Mode = 'paper';

export interface RiskSettings {
  /** Largest notional value of any single position. */
  maxPositionNotional: number;
  /** Fraction of equity committed per entry (0.02 = 2%). */
  riskFraction: number;
  /** Realized loss in one day that halts new entries. Exits still work. */
  maxDailyLoss: number;
  /** Runaway-loop protection. */
  maxOrdersPerDay: number;
  /** Skip orders smaller than this notional. */
  minOrderNotional: number;
}

export interface EngineSettings {
  mode: Mode;
  exchange: 'binance' | 'bybit' | 'okx';
  symbol: string;
  timeframe: string;
  pollSeconds: number;

  startingCash: number;
  feePct: number;
  slippagePct: number;

  fastPeriod: number;
  slowPeriod: number;

  risk: RiskSettings;
}

export const DEFAULT_SETTINGS: EngineSettings = {
  mode: 'paper',
  exchange: 'binance',
  symbol: 'BTC/USDT',
  timeframe: '1m',
  // 30s keeps the request rate polite and the battery cost sane; the strategy
  // works on closed candles so polling faster buys nothing.
  pollSeconds: 30,

  startingCash: 1000,
  feePct: 0.1,
  slippagePct: 0.02,

  fastPeriod: 12,
  slowPeriod: 26,

  risk: {
    maxPositionNotional: 100,
    riskFraction: 0.02,
    maxDailyLoss: 25,
    maxOrdersPerDay: 40,
    minOrderNotional: 5,
  },
};

export const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;

export function validateSettings(s: EngineSettings): string[] {
  const errors: string[] = [];

  if (s.fastPeriod >= s.slowPeriod) {
    errors.push('Fast period must be less than slow period');
  }
  if (s.pollSeconds < 5) {
    errors.push('Poll interval must be at least 5 seconds');
  }
  if (!/^[A-Z0-9]+\/[A-Z0-9]+$/i.test(s.symbol)) {
    errors.push('Symbol must look like BTC/USDT');
  }
  if (s.startingCash <= 0) {
    errors.push('Starting cash must be greater than zero');
  }

  // These mirror RiskConfig.validate() in the Python bot: a limit of zero is
  // rejected rather than treated as "unlimited".
  if (s.risk.maxPositionNotional <= 0) errors.push('Max position size must be > 0');
  if (s.risk.riskFraction <= 0 || s.risk.riskFraction > 1) {
    errors.push('Risk fraction must be between 0 and 1');
  }
  if (s.risk.maxDailyLoss <= 0) errors.push('Daily loss limit must be > 0');
  if (s.risk.maxOrdersPerDay <= 0) errors.push('Daily order cap must be > 0');
  if (s.risk.minOrderNotional < 0) errors.push('Minimum order size cannot be negative');

  return errors;
}
