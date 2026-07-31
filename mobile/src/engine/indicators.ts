/** Indicator maths. Pure functions, directly unit-testable off-device. */

export function sma(values: number[], period: number): number[] {
  if (period <= 0) throw new Error('period must be positive');
  if (values.length < period) return [];

  const out: number[] = [];
  let running = 0;
  for (let i = 0; i < period; i += 1) running += values[i];
  out.push(running / period);

  for (let i = period; i < values.length; i += 1) {
    running += values[i] - values[i - period];
    out.push(running / period);
  }
  return out;
}

/** Exponential moving average, seeded with the first `period` SMA. */
export function ema(values: number[], period: number): number[] {
  if (period <= 0) throw new Error('period must be positive');
  if (values.length < period) return [];

  const multiplier = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i += 1) seed += values[i];
  seed /= period;

  const out = [seed];
  for (let i = period; i < values.length; i += 1) {
    const prev = out[out.length - 1];
    out.push((values[i] - prev) * multiplier + prev);
  }
  return out;
}
