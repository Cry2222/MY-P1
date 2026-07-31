import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, SafeAreaView, StyleSheet, Text, View } from 'react-native';

import type { Connection } from './src/api/types';
import type { EngineSettings } from './src/engine/config';
import {
  startForegroundService,
  stopForegroundService,
  updateForegroundService,
} from './src/engine/foreground';
import { Journal } from './src/engine/journal';
import { TradingEngine } from './src/engine/runner';
import { loadSettings, saveSettings } from './src/engine/settingsStore';
import { DashboardScreen } from './src/screens/DashboardScreen';
import { ModeScreen } from './src/screens/ModeScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { SetupScreen } from './src/screens/SetupScreen';
import { LocalSource } from './src/source/local';
import { RemoteSource } from './src/source/remote';
import type { BotSource } from './src/source/types';
import { clearConnection, loadConnection, saveConnection } from './src/storage';
import { colors, space } from './src/theme';

type Screen = 'boot' | 'mode' | 'local' | 'remote-setup' | 'remote' | 'settings';

export default function App() {
  const [screen, setScreen] = useState<Screen>('boot');
  const [bootError, setBootError] = useState('');
  const [source, setSource] = useState<BotSource | null>(null);
  const [settings, setSettings] = useState<EngineSettings | null>(null);

  const engineRef = useRef<TradingEngine | null>(null);
  const journalRef = useRef<Journal | null>(null);

  /** Build the engine once and reuse it; it owns the journal and the loop. */
  const ensureEngine = useCallback(async (): Promise<TradingEngine> => {
    if (engineRef.current) return engineRef.current;
    const journal = journalRef.current ?? (await Journal.open());
    journalRef.current = journal;
    const loaded = await loadSettings(journal);
    setSettings(loaded);
    const engine = await TradingEngine.create(loaded, journal);
    engineRef.current = engine;
    return engine;
  }, []);

  const runHere = useCallback(async () => {
    const engine = await ensureEngine();
    setSource(new LocalSource(engine));
    setScreen('local');

    // The notification is the honest signal that this phone is trading; it is
    // also the only thing that stops Android suspending the loop.
    const s = engine.getSettings();
    await startForegroundService(`${s.symbol} ${s.timeframe} · paper`);
    await engine.start();
  }, [ensureEngine]);

  // Decide the opening screen from what was saved last time.
  useEffect(() => {
    (async () => {
      try {
        const journal = await Journal.open();
        journalRef.current = journal;
        const mode = await journal.getControl<'local' | 'remote' | null>('ui_mode', null);

        if (mode === 'local') {
          await runHere();
          return;
        }
        if (mode === 'remote') {
          const connection = await loadConnection();
          if (connection) {
            setSource(new RemoteSource(connection));
            setScreen('remote');
            return;
          }
        }
        setScreen('mode');
      } catch (e) {
        setBootError(e instanceof Error ? e.message : 'Could not start');
        setScreen('mode');
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rememberMode = useCallback(async (mode: 'local' | 'remote') => {
    await journalRef.current?.setControl('ui_mode', mode);
  }, []);

  const chooseLocal = useCallback(async () => {
    await rememberMode('local');
    await runHere();
  }, [rememberMode, runHere]);

  const chooseRemote = useCallback(async () => {
    await stopForegroundService();
    await engineRef.current?.stop();
    await rememberMode('remote');
    const existing = await loadConnection();
    if (existing) {
      setSource(new RemoteSource(existing));
      setScreen('remote');
    } else {
      setScreen('remote-setup');
    }
  }, [rememberMode]);

  const onRemoteConnected = useCallback(async (connection: Connection) => {
    await saveConnection(connection);
    await rememberMode('remote');
    setSource(new RemoteSource(connection));
    setScreen('remote');
  }, [rememberMode]);

  const switchMode = useCallback(async () => {
    if (screen === 'local') {
      await chooseRemote();
    } else {
      await clearConnection();
      await chooseLocal();
    }
  }, [screen, chooseLocal, chooseRemote]);

  const onSaveSettings = useCallback(async (next: EngineSettings) => {
    const journal = journalRef.current;
    if (journal) await saveSettings(journal, next);
    setSettings(next);
    await engineRef.current?.applySettings(next);
    await updateForegroundService(`${next.symbol} ${next.timeframe} · paper`);
    setScreen('local');
  }, []);

  const onResetHistory = useCallback(async () => {
    await engineRef.current?.resetHistory();
    setScreen('local');
  }, []);

  // Stop the service when the app is torn down, so a stopped bot never leaves
  // a notification claiming it is still trading.
  useEffect(() => () => void stopForegroundService(), []);

  let body: React.ReactNode;
  if (screen === 'boot') {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  } else if (screen === 'mode') {
    body = (
      <>
        {bootError ? <Text style={styles.bootError}>{bootError}</Text> : null}
        <ModeScreen onRunHere={chooseLocal} onConnectRemote={chooseRemote} />
      </>
    );
  } else if (screen === 'remote-setup') {
    body = <SetupScreen onConnected={onRemoteConnected} />;
  } else if (screen === 'settings' && settings) {
    body = (
      <SettingsScreen
        initial={settings}
        onSave={onSaveSettings}
        onCancel={() => setScreen('local')}
        onResetHistory={onResetHistory}
      />
    );
  } else if (source) {
    body = (
      <DashboardScreen
        source={source}
        onOpenSettings={() => setScreen('settings')}
        onSwitchMode={switchMode}
      />
    );
  } else {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />
      {body}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  bootError: {
    color: colors.warn,
    fontSize: 12,
    paddingHorizontal: space.xl,
    paddingTop: space.md,
  },
});
