/**
 * The screen you actually look at.
 *
 * Layout order is deliberate and matches how the screen gets read: state
 * first (is it running, is it live), then the money, then the chart, then
 * controls, then history. Someone glancing at a lock screen should get the
 * answer from the top two blocks alone.
 *
 * Polling rather than a socket: a phone's connection drops constantly, and a
 * poll that fails is a stale badge, while a dead socket is a screen that
 * silently lies. The staleness indicator is the whole point — it is worse to
 * show confident wrong numbers than to admit the last update was 40s ago.
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

import { ApiError, api } from '../api/client';
import type { Candle, Connection, FillRow, Status } from '../api/types';
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
import {
  colors,
  compactDuration,
  font,
  pnlColor,
  signed,
  space,
  timeAgo,
} from '../theme';

const POLL_MS = 6000;
const STALE_MS = 20000;

export function DashboardScreen({
  connection,
  onAuthFailure,
  onDisconnect,
}: {
  connection: Connection;
  onAuthFailure: () => void;
  onDisconnect: () => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [fills, setFills] = useState<FillRow[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmSpec | null>(null);
  const [notice, setNotice] = useState('');
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
      const [nextStatus, fillsBody] = await Promise.all([
        api.status(connection),
        api.fills(connection, 15),
      ]);
      if (!mounted.current) return;
      setStatus(nextStatus);
      setFills(fillsBody.fills);
      setUpdatedAt(Date.now());
      setError('');
    } catch (e) {
      if (!mounted.current) return;
      if (e instanceof ApiError && e.isAuthError) {
        onAuthFailure();
        return;
      }
      setError(e instanceof ApiError ? e.message : 'Update failed');
    }

    // Candles come from the exchange and can fail on their own while the rest
    // of the bot is healthy, so a chart outage must not blank the dashboard.
    try {
      const series = await api.candles(connection, 90);
      if (mounted.current) setCandles(series.candles);
    } catch {
      /* chart stays as-is */
    }
  }, [connection, onAuthFailure]);

  useEffect(() => {
    load();
    const poll = setInterval(load, POLL_MS);
    // Re-tick every second so "updated 12s ago" stays honest between polls.
    const clock = setInterval(() => setTick((n) => n + 1), 1000);
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') load();
    });
    return () => {
      clearInterval(poll);
      clearInterval(clock);
      sub.remove();
    };
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  async function control(
    action: 'pause' | 'resume' | 'kill' | 'revive',
  ): Promise<void> {
    setPending(action);
    setNotice('');
    try {
      const result = await api[action](connection);
      await load();
      if (action === 'kill') setNotice(result.message);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : 'Request failed');
    } finally {
      setPending(null);
    }
  }

  function confirmKill() {
    // A kill switch reached by one tap on a phone in a pocket is a hazard.
    setConfirm({
      title: 'Engage kill switch?',
      body:
        'This halts ALL orders including exits. Any open position becomes '
        + 'yours to close by hand on the exchange.',
      confirmLabel: 'Kill',
      variant: 'danger',
      onConfirm: () => control('kill'),
    });
  }

  function confirmDisconnect() {
    setConfirm({
      title: 'Forget this connection?',
      body: 'The saved token will be removed from this device.',
      confirmLabel: 'Forget',
      variant: 'danger',
      onConfirm: onDisconnect,
    });
  }

  const stale = updatedAt > 0 && Date.now() - updatedAt > STALE_MS;

  if (!status) {
    return (
      <View style={styles.loading}>
        <Text style={styles.loadingText}>
          {error || 'Connecting to your bot…'}
        </Text>
        {error ? (
          <Button label="Retry" variant="primary" onPress={load} style={styles.retry} />
        ) : null}
      </View>
    );
  }

  const net = status.realized_total + status.unrealized;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
        />
      }
    >
      {/* State — the first thing read */}
      <View style={styles.badges}>
        <Badge
          label={status.mode === 'live' ? 'LIVE' : 'PAPER'}
          color={status.mode === 'live' ? colors.live : colors.paper}
          filled={status.mode === 'live'}
        />
        {status.killed ? (
          <Badge label="KILLED" color={colors.danger} filled />
        ) : status.paused ? (
          <Badge label="PAUSED" color={colors.warn} />
        ) : (
          <Badge label="ACTIVE" color={colors.profit} />
        )}
        {stale ? <Badge label="STALE" color={colors.textMuted} /> : null}
      </View>

      {error ? <Text style={styles.errorBanner}>{error}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      {/* The money — hero figure */}
      <Card>
        <Text style={styles.heroLabel}>Net P&amp;L</Text>
        <Text style={[styles.hero, { color: pnlColor(net) }]}>
          {signed(net, 2)}
        </Text>
        <View style={styles.heroSplit}>
          <View style={styles.heroCell}>
            <Text style={styles.heroCellLabel}>Today</Text>
            <Text
              style={[styles.heroCellValue, { color: pnlColor(status.realized_today) }]}
            >
              {signed(status.realized_today, 2)}
            </Text>
          </View>
          <View style={styles.heroCell}>
            <Text style={styles.heroCellLabel}>Realized</Text>
            <Text
              style={[styles.heroCellValue, { color: pnlColor(status.realized_total) }]}
            >
              {signed(status.realized_total, 2)}
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
        {status.position_qty === 0 ? (
          <Empty message="Flat — no open position" />
        ) : (
          <>
            {/* Side is a word, not a colour. Teal and red are reserved for
                money on this screen — reusing them for direction would put
                two meanings on one channel. */}
            <Row label="Side" value={status.position_side.toUpperCase()} />
            <Row label="Quantity" value={status.position_qty.toFixed(8)} />
            <Row label="Entry" value={status.avg_price.toFixed(4)} />
            <Row label="Mark" value={status.last_price.toFixed(4)} />
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
      <View style={styles.controls}>
        {status.paused ? (
          <Button
            label="Resume"
            variant="primary"
            onPress={() => control('resume')}
            busy={pending === 'resume'}
            disabled={status.killed}
            style={styles.control}
          />
        ) : (
          <Button
            label="Pause"
            variant="warn"
            onPress={() => control('pause')}
            busy={pending === 'pause'}
            disabled={status.killed}
            style={styles.control}
          />
        )}
        {status.killed ? (
          <Button
            label="Revive"
            variant="primary"
            onPress={() => control('revive')}
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
      <Text style={styles.controlHint}>
        Pause stops new entries but still lets open positions exit. Kill stops
        everything, exits included.
      </Text>

      {/* Runtime */}
      <SectionTitle>Runtime</SectionTitle>
      <Card>
        <Row label="Strategy" value={status.strategy} />
        <Row label="Venue" value={status.venue} />
        <Row label="Timeframe" value={status.timeframe} />
        <Row label="Uptime" value={compactDuration(status.uptime_seconds)} />
        <Row label="Ticks" value={String(status.ticks)} />
        <Row
          label="Errors"
          value={String(status.errors)}
          valueColor={status.errors > 0 ? colors.warn : colors.text}
        />
        <Row label="Orders today" value={String(status.orders_today)} />
      </Card>

      {/* History */}
      <SectionTitle>Recent fills</SectionTitle>
      <Card>
        {fills.length === 0 ? (
          <Empty message="No fills yet" />
        ) : (
          fills.map((fill) => (
            <View key={fill.id} style={styles.fill}>
              <View style={styles.fillLeft}>
                <Text style={styles.fillSide}>{fill.side.toUpperCase()}</Text>
                <Text style={styles.fillQty}>
                  {fill.quantity.toFixed(6)} @ {fill.price.toFixed(2)}
                </Text>
              </View>
              <Text style={[styles.fillPnl, { color: pnlColor(fill.realized) }]}>
                {signed(fill.realized, 2)}
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
        <Button label="Forget connection" onPress={confirmDisconnect} />
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
  badges: { flexDirection: 'row', gap: space.sm, marginBottom: space.xs },
  errorBanner: {
    color: colors.warn,
    fontSize: 12,
    marginBottom: space.xs,
  },
  notice: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginBottom: space.xs,
  },
  heroLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  hero: {
    fontSize: 44,
    fontWeight: '800',
    fontFamily: font.mono,
    marginVertical: space.xs,
  },
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
  control: { flex: 1 },
  controlHint: {
    color: colors.textFaint,
    fontSize: 12,
    lineHeight: 17,
    marginTop: space.sm,
  },
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
