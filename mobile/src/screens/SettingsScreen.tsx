/**
 * Engine settings.
 *
 * Every risk limit is editable but none can be switched off — `validateSettings`
 * rejects zero the same way the Python `RiskConfig.validate()` does. Making a
 * limit removable through a text field would be the easiest way to lose money
 * in this whole app.
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

import { TIMEFRAMES, validateSettings, type EngineSettings } from '../engine/config';
import { Button, Card, SectionTitle } from '../components/primitives';
import { colors, font, radius, space } from '../theme';

const EXCHANGES = ['binance', 'bybit', 'okx'] as const;

function Field({
  label,
  value,
  onChange,
  hint,
  keyboardType = 'numeric',
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  keyboardType?: 'numeric' | 'default';
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType}
        autoCapitalize="characters"
        autoCorrect={false}
        style={styles.input}
        accessibilityLabel={label}
      />
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

function Choice<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.choices}>
        {options.map((option) => (
          <Button
            key={option}
            label={option}
            variant={option === value ? 'primary' : 'default'}
            onPress={() => onChange(option)}
            style={styles.choice}
          />
        ))}
      </View>
    </View>
  );
}

export function SettingsScreen({
  initial,
  onSave,
  onCancel,
  onResetHistory,
}: {
  initial: EngineSettings;
  onSave: (s: EngineSettings) => void;
  onCancel: () => void;
  onResetHistory: () => void;
}) {
  const [draft, setDraft] = useState<EngineSettings>(initial);
  const [errors, setErrors] = useState<string[]>([]);

  // Kept as text so a half-typed number does not get coerced to NaN mid-edit.
  const [text, setText] = useState({
    symbol: initial.symbol,
    pollSeconds: String(initial.pollSeconds),
    startingCash: String(initial.startingCash),
    fastPeriod: String(initial.fastPeriod),
    slowPeriod: String(initial.slowPeriod),
    feePct: String(initial.feePct),
    maxPositionNotional: String(initial.risk.maxPositionNotional),
    riskFraction: String(initial.risk.riskFraction * 100),
    maxDailyLoss: String(initial.risk.maxDailyLoss),
    maxOrdersPerDay: String(initial.risk.maxOrdersPerDay),
  });

  const num = (v: string, fallback: number) => {
    const parsed = Number(v);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  function save() {
    const next: EngineSettings = {
      ...draft,
      symbol: text.symbol.trim().toUpperCase(),
      pollSeconds: num(text.pollSeconds, initial.pollSeconds),
      startingCash: num(text.startingCash, initial.startingCash),
      fastPeriod: Math.round(num(text.fastPeriod, initial.fastPeriod)),
      slowPeriod: Math.round(num(text.slowPeriod, initial.slowPeriod)),
      feePct: num(text.feePct, initial.feePct),
      risk: {
        ...draft.risk,
        maxPositionNotional: num(text.maxPositionNotional, initial.risk.maxPositionNotional),
        riskFraction: num(text.riskFraction, initial.risk.riskFraction * 100) / 100,
        maxDailyLoss: num(text.maxDailyLoss, initial.risk.maxDailyLoss),
        maxOrdersPerDay: Math.round(num(text.maxOrdersPerDay, initial.risk.maxOrdersPerDay)),
      },
    };

    const problems = validateSettings(next);
    if (problems.length > 0) {
      setErrors(problems);
      return;
    }
    setErrors([]);
    onSave(next);
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Settings</Text>
        <Text style={styles.subtitle}>Paper trading with live market prices.</Text>

        <SectionTitle>Market</SectionTitle>
        <Card>
          <Choice
            label="Exchange"
            options={EXCHANGES}
            value={draft.exchange}
            onChange={(exchange) => setDraft({ ...draft, exchange })}
          />
          <Field
            label="Symbol"
            value={text.symbol}
            onChange={(v) => setText({ ...text, symbol: v })}
            keyboardType="default"
            hint="Format: BTC/USDT"
          />
          <Choice
            label="Timeframe"
            options={TIMEFRAMES}
            value={draft.timeframe as (typeof TIMEFRAMES)[number]}
            onChange={(timeframe) => setDraft({ ...draft, timeframe })}
          />
          <Field
            label="Check every (seconds)"
            value={text.pollSeconds}
            onChange={(v) => setText({ ...text, pollSeconds: v })}
            hint="Lower uses more battery. The strategy works on closed candles, so faster than the timeframe buys nothing."
          />
        </Card>

        <SectionTitle>Strategy</SectionTitle>
        <Card>
          <Field
            label="Fast EMA"
            value={text.fastPeriod}
            onChange={(v) => setText({ ...text, fastPeriod: v })}
          />
          <Field
            label="Slow EMA"
            value={text.slowPeriod}
            onChange={(v) => setText({ ...text, slowPeriod: v })}
            hint="Must be larger than the fast period. Buys when fast crosses above slow."
          />
        </Card>

        <SectionTitle>Risk limits</SectionTitle>
        <Card>
          <Field
            label="Max position size"
            value={text.maxPositionNotional}
            onChange={(v) => setText({ ...text, maxPositionNotional: v })}
            hint="Largest value of any single position, in quote currency."
          />
          <Field
            label="Risk per trade (%)"
            value={text.riskFraction}
            onChange={(v) => setText({ ...text, riskFraction: v })}
            hint="Share of equity committed per entry."
          />
          <Field
            label="Daily loss limit"
            value={text.maxDailyLoss}
            onChange={(v) => setText({ ...text, maxDailyLoss: v })}
            hint="Stops new entries once the day is down this much. Exits still work."
          />
          <Field
            label="Max orders per day"
            value={text.maxOrdersPerDay}
            onChange={(v) => setText({ ...text, maxOrdersPerDay: v })}
            hint="Runaway protection."
          />
          <Text style={styles.note}>
            None of these can be set to zero. A limit that can be switched off is
            not a limit.
          </Text>
        </Card>

        <SectionTitle>Simulation</SectionTitle>
        <Card>
          <Field
            label="Starting balance"
            value={text.startingCash}
            onChange={(v) => setText({ ...text, startingCash: v })}
          />
          <Field
            label="Fee per side (%)"
            value={text.feePct}
            onChange={(v) => setText({ ...text, feePct: v })}
            hint="Applied to both entry and exit, so results stay pessimistic."
          />
        </Card>

        {errors.length > 0 ? (
          <View style={styles.errors}>
            {errors.map((e) => (
              <Text key={e} style={styles.error}>
                • {e}
              </Text>
            ))}
          </View>
        ) : null}

        <View style={styles.actions}>
          <Button label="Cancel" onPress={onCancel} style={styles.action} />
          <Button label="Save" variant="primary" onPress={save} style={styles.action} />
        </View>

        <SectionTitle>Danger zone</SectionTitle>
        <Button label="Clear all trade history" variant="danger" onPress={onResetHistory} />
        <Text style={styles.note}>
          Deletes every fill and resets the simulated balance. Settings and the
          kill switch are kept.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  content: { padding: space.lg, paddingBottom: space.xxl * 2, gap: space.sm },
  title: { color: colors.text, fontSize: 28, fontWeight: '800' },
  subtitle: { color: colors.textMuted, fontSize: 14, marginBottom: space.sm },
  field: { marginBottom: space.md },
  label: { color: colors.text, fontSize: 13, fontWeight: '700', marginBottom: space.xs },
  input: {
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    color: colors.text,
    fontFamily: font.mono,
    fontSize: 15,
    minHeight: 46,
    paddingHorizontal: space.md,
  },
  hint: { color: colors.textFaint, fontSize: 11, lineHeight: 16, marginTop: space.xs },
  note: { color: colors.textFaint, fontSize: 11, lineHeight: 16, marginTop: space.sm },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  choice: { minHeight: 40, paddingHorizontal: space.md, minWidth: 64 },
  errors: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.loss,
    borderRadius: radius.md,
    padding: space.md,
    marginTop: space.sm,
  },
  error: { color: colors.loss, fontSize: 13, lineHeight: 19 },
  actions: { flexDirection: 'row', gap: space.md, marginTop: space.lg },
  action: { flex: 1 },
});
