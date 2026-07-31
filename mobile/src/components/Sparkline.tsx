/**
 * Price sparkline.
 *
 * One series, so there is no legend — the header names the symbol, and the
 * current value is direct-labelled at the end of the line. Direction is
 * carried by the signed change figure beside it, never by the line's colour:
 * a single accent hue avoids making colour the only channel, and avoids the
 * green/red pair entirely.
 *
 * Deliberately no grid, no y-axis ticks, no value labels on every point. A
 * sparkline answers "which way and roughly how much", and chrome only makes
 * that harder to read at a glance.
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';

import type { Candle } from '../engine/models';
import { colors, font, signed, space } from '../theme';

interface Props {
  candles: Candle[];
  height?: number;
  symbol: string;
}

function buildPath(values: number[], width: number, height: number, pad: number) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = (width - pad * 2) / Math.max(values.length - 1, 1);

  const points = values.map((value, index) => ({
    x: pad + index * stepX,
    y: pad + (1 - (value - min) / span) * (height - pad * 2),
  }));

  const line = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');

  const area =
    `${line} L${points[points.length - 1].x.toFixed(2)},${height - pad} ` +
    `L${points[0].x.toFixed(2)},${height - pad} Z`;

  return { line, area, last: points[points.length - 1] };
}

export function Sparkline({ candles, height = 96, symbol }: Props) {
  // A fixed viewBox width with preserveAspectRatio="none" lets the SVG scale
  // to whatever the phone's width is without measuring the layout first.
  const WIDTH = 320;
  const PAD = 6;

  if (candles.length < 2) {
    return (
      <View style={[styles.placeholder, { height }]}>
        <Text style={styles.placeholderText}>No price history yet</Text>
      </View>
    );
  }

  const values = candles.map((c) => c.close);
  const { line, area, last } = buildPath(values, WIDTH, height, PAD);

  const first = values[0];
  const current = values[values.length - 1];
  const change = current - first;
  const changePct = first ? (change / first) * 100 : 0;

  return (
    <View>
      <View style={styles.header}>
        <Text style={styles.symbol}>{symbol}</Text>
        <View style={styles.headerRight}>
          <Text style={styles.price}>{current.toFixed(2)}</Text>
          <Text
            style={[
              styles.change,
              { color: change >= 0 ? colors.profit : colors.loss },
            ]}
            // The sign is in the text, so a screen reader and a colourblind
            // reader get the same information the colour carries.
            accessibilityLabel={`${change >= 0 ? 'up' : 'down'} ${Math.abs(
              changePct,
            ).toFixed(2)} percent over the shown period`}
          >
            {signed(changePct, 2)}%
          </Text>
        </View>
      </View>

      <Svg
        width="100%"
        height={height}
        viewBox={`0 0 ${WIDTH} ${height}`}
        preserveAspectRatio="none"
      >
        <Defs>
          <LinearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0.28" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="0" />
          </LinearGradient>
        </Defs>

        <Path d={area} fill="url(#fade)" />
        <Path
          d={line}
          stroke={colors.accent}
          strokeWidth={2}
          fill="none"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {/* Surface-coloured ring so the end marker stays visible wherever the
            line happens to finish. */}
        <Circle cx={last.x} cy={last.y} r={5} fill={colors.surface} />
        <Circle cx={last.x} cy={last.y} r={3.5} fill={colors.accent} />
      </Svg>

      <Text style={styles.footnote}>
        last {candles.length} candles · low {Math.min(...values).toFixed(2)} ·
        high {Math.max(...values).toFixed(2)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginBottom: space.sm,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: space.sm,
  },
  symbol: {
    color: colors.textMuted,
    fontSize: 13,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  price: {
    color: colors.text,
    fontSize: 22,
    fontWeight: '700',
    fontFamily: font.mono,
  },
  change: {
    fontSize: 14,
    fontWeight: '700',
    fontFamily: font.mono,
  },
  footnote: {
    color: colors.textFaint,
    fontSize: 11,
    marginTop: space.xs,
  },
  placeholder: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  placeholderText: {
    color: colors.textFaint,
    fontSize: 13,
  },
});
