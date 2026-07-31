import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, SafeAreaView, StyleSheet, View } from 'react-native';

import type { Connection } from './src/api/types';
import { DashboardScreen } from './src/screens/DashboardScreen';
import { SetupScreen } from './src/screens/SetupScreen';
import { clearConnection, loadConnection, saveConnection } from './src/storage';
import { colors } from './src/theme';

export default function App() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadConnection()
      .then(setConnection)
      .finally(() => setLoaded(true));
  }, []);

  const onConnected = useCallback(async (next: Connection) => {
    await saveConnection(next);
    setConnection(next);
  }, []);

  const onDisconnect = useCallback(async () => {
    await clearConnection();
    setConnection(null);
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />
      {!loaded ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : connection ? (
        <DashboardScreen
          connection={connection}
          // A rejected token means the bot rotated it. Drop straight back to
          // setup rather than leaving a dashboard that cannot refresh.
          onAuthFailure={onDisconnect}
          onDisconnect={onDisconnect}
        />
      ) : (
        <SetupScreen onConnected={onConnected} />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
