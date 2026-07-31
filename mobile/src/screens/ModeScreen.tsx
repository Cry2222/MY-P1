/**
 * First-run choice: run the bot here, or drive one on a server.
 *
 * The on-phone engine is the default because it needs nothing else installed.
 * The server option stays because the trade-off is real and worth naming: a
 * phone that runs out of battery stops trading, and a server does not.
 */

import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, Card } from '../components/primitives';
import { colors, space } from '../theme';

export function ModeScreen({
  onRunHere,
  onConnectRemote,
}: {
  onRunHere: () => void;
  onConnectRemote: () => void;
}) {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text style={styles.title}>MY-P1</Text>
      <Text style={styles.subtitle}>Where should the bot run?</Text>

      <Card style={styles.card}>
        <Text style={styles.optionTitle}>On this phone</Text>
        <Text style={styles.optionBody}>
          The trading engine runs inside this app. Nothing else to install, and
          no network exposure — it talks only to the exchange for prices.
        </Text>
        <Text style={styles.optionNote}>
          Android needs a permanent notification to keep it running in the
          background, and it stops if the phone dies.
        </Text>
        <Button
          label="Run on this phone"
          variant="primary"
          onPress={onRunHere}
          style={styles.action}
        />
      </Card>

      <Card style={styles.card}>
        <Text style={styles.optionTitle}>On a server</Text>
        <Text style={styles.optionBody}>
          Connect to a Python bot running elsewhere — a VPS, or Termux on this
          phone. This app becomes a remote control.
        </Text>
        <Text style={styles.optionNote}>
          Keeps trading when your phone is off. Needs the bot set up separately.
        </Text>
        <Button label="Connect to a server" onPress={onConnectRemote} style={styles.action} />
      </Card>

      <View style={styles.footer}>
        <Text style={styles.footnote}>
          Both modes are paper trading: simulated fills against live market
          prices. No exchange account, no API keys, no real money.
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    padding: space.xl,
    paddingTop: space.xxl * 2,
    gap: space.md,
    backgroundColor: colors.bg,
    flexGrow: 1,
  },
  title: { color: colors.text, fontSize: 34, fontWeight: '800', letterSpacing: -0.5 },
  subtitle: { color: colors.textMuted, fontSize: 15, marginBottom: space.lg },
  card: { gap: space.xs },
  optionTitle: { color: colors.text, fontSize: 17, fontWeight: '700' },
  optionBody: { color: colors.textMuted, fontSize: 14, lineHeight: 20, marginTop: space.xs },
  optionNote: { color: colors.textFaint, fontSize: 12, lineHeight: 17, marginTop: space.sm },
  action: { marginTop: space.lg },
  footer: { marginTop: space.lg },
  footnote: { color: colors.textFaint, fontSize: 12, lineHeight: 18, textAlign: 'center' },
});
