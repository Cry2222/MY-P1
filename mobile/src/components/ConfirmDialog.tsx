/**
 * Confirmation modal.
 *
 * Deliberately not React Native's `Alert.alert`. Alert with buttons is a
 * no-op under react-native-web, which means the kill switch would silently do
 * nothing in the web preview — the single worst control to have a
 * platform-dependent failure mode. A Modal behaves identically everywhere and
 * can be driven by a test.
 */

import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radius, space } from '../theme';
import { Button } from './primitives';

export interface ConfirmSpec {
  title: string;
  body: string;
  confirmLabel: string;
  variant?: 'danger' | 'primary';
  onConfirm: () => void;
}

export function ConfirmDialog({
  spec,
  onDismiss,
}: {
  spec: ConfirmSpec | null;
  onDismiss: () => void;
}) {
  return (
    <Modal
      visible={spec !== null}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}
    >
      <Pressable style={styles.backdrop} onPress={onDismiss} accessibilityLabel="Dismiss">
        {/* Stop taps inside the sheet from closing it. */}
        <Pressable style={styles.sheet} onPress={() => {}}>
          <Text style={styles.title}>{spec?.title}</Text>
          <Text style={styles.body}>{spec?.body}</Text>
          <View style={styles.actions}>
            <Button label="Cancel" onPress={onDismiss} style={styles.action} />
            <Button
              label={spec?.confirmLabel ?? 'Confirm'}
              variant={spec?.variant ?? 'danger'}
              onPress={() => {
                onDismiss();
                spec?.onConfirm();
              }}
              style={styles.action}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xl,
  },
  sheet: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.xl,
  },
  title: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
    marginBottom: space.sm,
  },
  body: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: space.xl,
  },
  actions: { flexDirection: 'row', gap: space.md },
  action: { flex: 1 },
});
