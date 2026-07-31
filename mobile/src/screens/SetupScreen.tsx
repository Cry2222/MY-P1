/**
 * First-run connection setup.
 *
 * The connection is verified against the live bot before it is saved, so a
 * typo surfaces here rather than as a dead dashboard later.
 */

import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ApiError, normaliseBaseUrl, verifyConnection } from '../api/client';
import type { Connection } from '../api/types';
import { Button, Card } from '../components/primitives';
import { isSecureStorageAvailable } from '../storage';
import { colors, font, radius, space } from '../theme';

/** The bot running on this same phone under Termux — see docs/on-device.md. */
const LOCAL_URL = 'http://127.0.0.1:8333';

export function SetupScreen({
  onConnected,
  initial,
}: {
  onConnected: (connection: Connection) => void;
  initial?: Connection | null;
}) {
  const [url, setUrl] = useState(initial?.baseUrl ?? LOCAL_URL);
  const [token, setToken] = useState(initial?.token ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');

  async function connect() {
    setBusy(true);
    setError('');
    setOk('');
    try {
      const connection = { baseUrl: normaliseBaseUrl(url), token: token.trim() };
      const health = await verifyConnection(connection);
      setOk(`Connected — ${health.mode} mode, v${health.version}`);
      onConnected(connection);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not connect');
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>MY-P1</Text>
        <Text style={styles.subtitle}>Connect to your trading bot</Text>

        <Card style={styles.card}>
          <Text style={styles.label}>Server address</Text>
          <TextInput
            value={url}
            onChangeText={setUrl}
            placeholder="http://127.0.0.1:8333"
            placeholderTextColor={colors.textFaint}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            style={styles.input}
            accessibilityLabel="Server address"
          />
          <View style={styles.presets}>
            <Button
              label="This phone"
              onPress={() => setUrl(LOCAL_URL)}
              style={styles.preset}
            />
            <Button
              label="My server"
              onPress={() => setUrl('http://100.')}
              style={styles.preset}
            />
          </View>
          <Text style={styles.hint}>
            <Text style={styles.hintStrong}>This phone</Text> — the bot is
            running here under Termux. Nothing leaves the device.
            {'\n'}
            <Text style={styles.hintStrong}>My server</Text> — the bot is on a
            VPS. Use its Tailscale address; the API binds to loopback and is not
            meant to face the open internet.
          </Text>

          <Text style={[styles.label, styles.labelSpaced]}>API token</Text>
          <TextInput
            value={token}
            onChangeText={setToken}
            placeholder="MYP1_API_TOKEN"
            placeholderTextColor={colors.textFaint}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            style={styles.input}
            accessibilityLabel="API token"
          />
          <Text style={styles.hint}>
            The value of MYP1_API_TOKEN from your bot&apos;s .env file.
          </Text>

          {error ? <Text style={styles.error}>{error}</Text> : null}
          {ok ? <Text style={styles.ok}>{ok}</Text> : null}

          <Button
            label="Connect"
            variant="primary"
            onPress={connect}
            busy={busy}
            disabled={!url.trim() || !token.trim()}
            style={styles.connect}
          />
        </Card>

        {!isSecureStorageAvailable ? (
          <Text style={styles.warning}>
            Running in a browser — the token is stored in localStorage, not the
            device keystore. Use the phone build for anything real.
          </Text>
        ) : (
          <Text style={styles.footnote}>
            The token is kept in the device keystore.
          </Text>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  content: {
    padding: space.xl,
    paddingTop: space.xxl * 2,
    gap: space.md,
  },
  title: {
    color: colors.text,
    fontSize: 34,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: 15,
    marginBottom: space.lg,
  },
  card: { gap: space.xs },
  label: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
    marginBottom: space.xs,
  },
  labelSpaced: { marginTop: space.lg },
  input: {
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    color: colors.text,
    fontFamily: font.mono,
    fontSize: 14,
    minHeight: 48,
    paddingHorizontal: space.md,
  },
  hint: {
    color: colors.textFaint,
    fontSize: 12,
    marginTop: space.xs,
    lineHeight: 17,
  },
  hintStrong: {
    color: colors.textMuted,
    fontWeight: '700',
  },
  presets: {
    flexDirection: 'row',
    gap: space.sm,
    marginTop: space.sm,
  },
  preset: {
    flex: 1,
    minHeight: 40,
  },
  connect: { marginTop: space.xl },
  error: {
    color: colors.loss,
    fontSize: 13,
    marginTop: space.md,
    fontWeight: '600',
  },
  ok: {
    color: colors.profit,
    fontSize: 13,
    marginTop: space.md,
    fontWeight: '600',
  },
  warning: {
    color: colors.warn,
    fontSize: 12,
    lineHeight: 17,
    marginTop: space.md,
  },
  footnote: {
    color: colors.textFaint,
    fontSize: 12,
    marginTop: space.md,
  },
});
