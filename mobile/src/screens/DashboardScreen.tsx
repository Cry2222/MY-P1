/**
 * The screen you actually look at.
 *
 * Layout order is deliberate and matches how the screen gets read: state
 * first (is it running, is it trading), then the money, then the chart, then
 * controls, then history. Someone glancing at a lock screen should get the
 * answer from the top two blocks alone.
 *
 * It reads through `BotSource` and does not know whether the bot is the engine
 * inside this app or a Python bot on a server.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppState,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { ApiError } from '../api/client';
import type { Candle } from '../engine/models';
import type { EngineStatus } from '../engine/runner';
import { ConfirmDialog, type ConfirmSpec } from '../components/ConfirmDialog';
import { Sparkline } from '../components/Sparkline';
import {
  Badge,
  Button,
  Card,
  Empty,
  Row,
  SectionTitle,
} from '../components/primitives';
import type { BotSource, FillView } from '../source/types';
import {
  colors,
  compactDuration,
  font,
  pnlColor,
  signed,
  space,
  timeAgo,
} from '../theme';

const POLL_MS = 5000;
const STALE_MS = 20000;

export function DashboardScreen({
  source,
  onOpenSettings,
  onSwitchMode,
}: {
  source: BotSource;
  onOpenSettings: () => void;
  onSwitchMode: () => void;
}) {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [fills, setFills] = useState<FillView[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [updatedAt, setUpdatedAt] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);
  const [, setTick] = useState(0);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const [nextStatus, nextFills] = await Promise.all([source.status(), source.fills(15)]);
      if (!mounted.current) return;
      setStatus(nextStatus);
      setFills(nextFills);
      setUpdatedAt(Date.now());
      setError('');
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof ApiError || e instanceof Error ? e.message : 'Update failed');
    }

    // Candles come from the exchange and can fail on their own while the rest
    // of the bot is healthy, so a chart outage must not blank the dashboard.
    try {
      const series = await source.candles(90);
      if (mounted.current) setCandles(series);
    } catch {
      /* chart stays as-is */
    }
  }, [source]);

  useEffect(() => {
    load();
    const poll = setInterval(load, POLL_MS);
    // Re-tick every second so "updated 12s ago" stays honest between polls.
    const clock = setInterval(() => setTick((n) => n + 1), 1000);
    const appState = AppState.addEventListener('change', (s) => {
      if (s === 'active') load();
    });
    const unsubscribe = source.subscribe?.(() => load());
    return () => {
      clearInterval(poll);
      clearInterval(clock);
      appState.remove();
      unsubscribe?.();
    };
  }, [load, source]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  async function act(name: string, fn: () => Promise<void>, message?: string) {
    setPending(name);
    setNotice('');
    try {
      await fn();
      await load();
      if (message) setNotice(message);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setPending(null);
    }
  }

  function confirmKill() {
    // A kill switch reached by one tap on a phone in a pocket is a hazard.
    setConfirm({
      title: 'Engage kill switch?',
      body:
        'This halts ALL orders including exits. Any open position stays open '
        + 'until you close it yourself.',
      confirmLabel: 'Kill',
      variant: 'danger',
      onConfirm: () =>
        act('kill', () => source.kill(), 'Kill switch engaged. No orders will be placed.'),
    });
  }

  const stale = updatedAt > 0 && Date.now() - updatedAt > STALE_MS;

  if (!status) {
    return (
      <View style={styles.loading}>
        <Text style={styles.loadingText}>{error || 'Starting…'}</Text>
        {error ? (
          <Button label="Retry" variant="primary" onPress={load} style={styles.retry} />
        ) : null}
      </View>
    );
  }

  const net = status.realizedTotal + status.unrealized;
  const isLocal = source.kind === 'local';

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
      }
    >
      {/* State — the first thing read */}
      <View style={styles.badges}>
        <Badge label="PAPER" color={colors.paper} />
        {status.killed ? (
          <Badge label="KILLED" color={colors.danger} filled />
        ) : status.paused ? (
          <Badge label="PAUSED" color={colors.warn} />
        ) : status.running ? (
          <Badge label="RUNNING" color={colors.profit} />
        ) : (
          <Badge label="STOPPED" color={colors.textMuted} />
        )}
        {stale ? <Badge label="STALE" color={colors.textMuted} /> : null}
      </View>

      <Text style={styles.sourceLine}>
        {source.label} · {status.exchange} · {status.symbol} {status.timeframe}
      </Text>

      {error ? <Text style={styles.errorBanner}>{error}</Text> : null}
      {status.lastError && !error ? (
        <Text style={styles.errorBanner}>{status.lastError}</Text>
      ) : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      {/* The money — hero figure */}
      <Card>
        <Text style={styles.heroLabel}>Net P&amp;L</Text>
        <Text style={[styles.hero, { color: pnlColor(net) }]}>{signed(net, 2)}</Text>
        <View style={styles.heroSplit}>
          <View style={styles.heroCell}>
            <Text style={styles.heroCellLabel}>Today</Text>
            <Text style={[styles.heroCellValue, { color: pnlColor(status.realizedToday) }]}>
              {signed(status.realizedToday, 2)}
            </Text>
          </View>
          <View style={styles.heroCell}>
            <Text style={styles.heroCellLabel}>Realized</Text>
            <Text style={[styles.heroCellValue, { color: pnlColor(status.realizedTotal) }]}>
              {signed(status.realizedTotal, 2)}
            </Text>
          </View>
          <View style={styles.heroCell}>
            <Text style={styles.heroCellLabel}>Open</Text>
            <Text style={[styles.heroCellValue, { color: pnlColor(status.unrealized) }]}>
              {signed(status.unrealized, 2)}
            </Text>
          </View>
        </View>
      </Card>

      {/* Price */}
      <Card>
        <Sparkline candles={candles} symbol={status.symbol} />
      </Card>

      {/* Position */}
      <SectionTitle>Position</SectionTitle>
      <Card>
        {status.positionQty === 0 ? (
          <Empty message="Flat — no open position" />
        ) : (
          <>
            {/* Side is a word, not a colour. Teal and red are reserved for
                money on this screen. */}
            <Row label="Side" value={status.positionSide.toUpperCase()} />
            <Row label="Quantity" value={status.positionQty.toFixed(8)} />
            <Row label="Entry" value={status.avgPrice.toFixed(4)} />
            <Row label="Mark" value={status.lastPrice.toFixed(4)} />
            <Row
              label="Unrealized"
              value={signed(status.unrealized, 4)}
              valueColor={pnlColor(status.unrealized)}
            />
          </>
        )}
      </Card>

      {/* Controls */}
      <SectionTitle>Controls</SectionTitle>
      {isLocal ? (
        <View style={styles.controls}>
          {status.running ? (
            <Button
              label="Stop bot"
              variant="warn"
              onPress={() => act('stop', () => source.stop!(), 'Bot stopped.')}
              busy={pending === 'stop'}
              style={styles.control}
            />
          ) : (
            <Button
              label="Start bot"
              variant="primary"
              onPress={() => act('start', () => source.start!(), 'Bot started.')}
              busy={pending === 'start'}
              disabled={status.killed}
              style={styles.control}
            />
          )}
          {status.killed ? (
            <Button
              label="Revive"
              variant="primary"
              onPress={() => act('revive', () => source.revive(), 'Kill switch released.')}
              busy={pending === 'revive'}
              style={styles.control}
            />
          ) : (
            <Button
              label="Kill"
              variant="danger"
              onPress={confirmKill}
              busy={pending === 'kill'}
              style={styles.control}
            />
          )}
        </View>
      ) : (
        <View style={styles.controls}>
          {status.paused ? (
            <Button
              label="Resume"
              variant="primary"
              onPress={() => act('resume', () => source.resume(), 'Resumed.')}
              busy={pending === 'resume'}
              disabled={status.killed}
              style={styles.control}
            />
          ) : (
            <Button
              label="Pause"
              variant="warn"
              onPress={() => act('pause', () => source.pause(), 'Paused.')}
              busy={pending === 'pause'}
              disabled={status.killed}
              style={styles.control}
            />
          )}
          {status.killed ? (
            <Button
              label="Revive"
              variant="primary"
              onPress={() => act('revive', () => source.revive(), 'Kill switch released.')}
              busy={pending === 'revive'}
              style={styles.control}
            />
          ) : (
            <Button
              label="Kill"
              variant="danger"
              onPress={confirmKill}
              busy={pending === 'kill'}
              style={styles.control}
            />
          )}
        </View>
      )}

      {isLocal && !status.killed ? (
        <View style={styles.controlsSecond}>
          {status.paused ? (
            <Button
              label="Allow new entries"
              onPress={() => act('resume', () => source.resume(), 'New entries allowed.')}
              busy={pending === 'resume'}
              style={styles.control}
            />
          ) : (
            <Button
              label="Pause new entries"
              onPress={() => act('pause', () => source.pause(), 'Paused. Exits still run.')}
              busy={pending === 'pause'}
              style={styles.control}
            />
          )}
        </View>
      ) : null}

      <Text style={styles.controlHint}>
        Pause stops new entries but still lets an open position exit. Kill stops
        everything, exits included.
      </Text>

      {/* Runtime */}
      <SectionTitle>Runtime</SectionTitle>
      <Card>
        <Row label="Strategy" value={status.strategy} />
        <Row label="Balance" value={status.equity > 0 ? status.equity.toFixed(2) : '—'} />
        <Row
          label="Uptime"
          value={status.startedAt ? compactDuration((Date.now() - status.startedAt) / 1000) : '—'}
        />
        <Row label="Checks" value={String(status.ticks)} />
        <Row
          label="Errors"
          value={String(status.errors)}
          valueColor={status.errors > 0 ? colors.warn : colors.text}
        />
        <Row label="Orders today" value={String(status.ordersToday)} />
      </Card>

      {/* History */}
      <SectionTitle>Recent fills</SectionTitle>
      <Card>
        {fills.length === 0 ? (
          <Empty message="No trades yet" />
        ) : (
          fills.map((f) => (
            <View key={f.id} style={styles.fill}>
              <View style={styles.fillLeft}>
                <Text style={styles.fillSide}>{f.side.toUpperCase()}</Text>
                <Text style={styles.fillQty}>
                  {f.quantity.toFixed(6)} @ {f.price.toFixed(2)}
                </Text>
              </View>
              <Text style={[styles.fillPnl, { color: pnlColor(f.realized) }]}>
                {signed(f.realized, 2)}
              </Text>
            </View>
          ))
        )}
      </Card>

      <ConfirmDialog spec={confirm} onDismiss={() => setConfirm(null)} />

      <View style={styles.footer}>
        <Text style={styles.updated}>
          {updatedAt ? `Updated ${timeAgo(updatedAt)}` : 'Never updated'}
        </Text>
        {isLocal ? <Button label="Settings" onPress={onOpenSettings} /> : null}
        <Button label={isLocal ? 'Connect to a server instead' : 'Run on this phone instead'} onPress={onSwitchMode} />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: space.lg, paddingBottom: space.xxl * 2, gap: space.sm },
  loading: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xl,
  },
  loadingText: { color: colors.textMuted, fontSize: 15, textAlign: 'center' },
  retry: { marginTop: space.lg, minWidth: 140 },
  badges: { flexDirection: 'row', gap: space.sm },
  sourceLine: { color: colors.textFaint, fontSize: 12, marginBottom: space.xs },
  errorBanner: { color: colors.warn, fontSize: 12, marginBottom: space.xs },
  notice: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginBottom: space.xs },
  heroLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  hero: { fontSize: 44, fontWeight: '800', fontFamily: font.mono, marginVertical: space.xs },
  heroSplit: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.border,
    marginTop: space.sm,
    paddingTop: space.md,
  },
  heroCell: { flex: 1 },
  heroCellLabel: { color: colors.textFaint, fontSize: 11, marginBottom: 2 },
  heroCellValue: { fontSize: 15, fontWeight: '700', fontFamily: font.mono },
  controls: { flexDirection: 'row', gap: space.md },
  controlsSecond: { flexDirection: 'row', gap: space.md, marginTop: space.sm },
  control: { flex: 1 },
  controlHint: { color: colors.textFaint, fontSize: 12, lineHeight: 17, marginTop: space.sm },
  fill: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: space.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  fillLeft: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  fillSide: { color: colors.text, fontSize: 12, fontWeight: '800', width: 38 },
  fillQty: { color: colors.textMuted, fontSize: 13, fontFamily: font.mono },
  fillPnl: { fontSize: 13, fontWeight: '700', fontFamily: font.mono },
  footer: { marginTop: space.xl, gap: space.md },
  updated: { color: colors.textFaint, fontSize: 12, textAlign: 'center' },
});
