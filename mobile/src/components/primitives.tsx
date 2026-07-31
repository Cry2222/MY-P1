import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ViewStyle,
} from 'react-native';

import { colors, font, radius, space } from '../theme';

export function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Badge({
  label,
  color = colors.accent,
  filled = false,
}: {
  label: string;
  color?: string;
  filled?: boolean;
}) {
  return (
    <View
      style={[
        styles.badge,
        { borderColor: color, backgroundColor: filled ? color : 'transparent' },
      ]}
    >
      <Text
        style={[styles.badgeText, { color: filled ? colors.bg : color }]}
        accessibilityLabel={label}
      >
        {label}
      </Text>
    </View>
  );
}

export function Row({
  label,
  value,
  valueColor = colors.text,
  mono = true,
}: {
  label: string;
  value: string;
  valueColor?: string;
  mono?: boolean;
}) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text
        style={[
          styles.rowValue,
          { color: valueColor },
          mono && { fontFamily: font.mono },
        ]}
      >
        {value}
      </Text>
    </View>
  );
}

export function Button({
  label,
  onPress,
  variant = 'default',
  disabled = false,
  busy = false,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: 'default' | 'primary' | 'danger' | 'warn';
  disabled?: boolean;
  busy?: boolean;
  style?: ViewStyle;
}) {
  // Border and label are separate on purpose. A neutral button should sit
  // back visually, but its label still has to be readable — tinting the text
  // with the recessive border colour makes it almost invisible.
  const border = {
    default: colors.border,
    primary: colors.accent,
    danger: colors.danger,
    warn: colors.warn,
  }[variant];

  const label_color = {
    default: colors.text,
    primary: colors.accent,
    danger: colors.danger,
    warn: colors.warn,
  }[variant];

  const inactive = disabled || busy;

  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy }}
      accessibilityLabel={label}
      style={({ pressed }) => [
        styles.button,
        {
          borderColor: border,
          backgroundColor: pressed ? colors.surfaceRaised : 'transparent',
          opacity: inactive ? 0.4 : 1,
        },
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={label_color} />
      ) : (
        <Text style={[styles.buttonText, { color: label_color }]}>{label}</Text>
      )}
    </Pressable>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <Text style={styles.sectionTitle}>{children}</Text>;
}

export function Empty({ message }: { message: string }) {
  return <Text style={styles.empty}>{message}</Text>;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.lg,
  },
  badge: {
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: space.md,
    paddingVertical: 3,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.6,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 7,
  },
  rowLabel: {
    color: colors.textMuted,
    fontSize: 14,
  },
  rowValue: {
    fontSize: 14,
    fontWeight: '600',
  },
  button: {
    // 48pt minimum touch target — this includes a kill switch, and it gets
    // pressed one-handed, in a hurry, on a moving train.
    minHeight: 48,
    borderWidth: 1.5,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
  },
  buttonText: {
    fontSize: 15,
    fontWeight: '700',
  },
  sectionTitle: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: space.sm,
    marginTop: space.lg,
  },
  empty: {
    color: colors.textFaint,
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: space.xl,
  },
});
