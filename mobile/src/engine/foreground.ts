/**
 * Android foreground service.
 *
 * Android suspends a normal app within minutes of it leaving the screen, which
 * for a trading loop means an open position nobody is managing. A foreground
 * service — the mechanism music players use — keeps the process alive, at the
 * cost of a permanent notification. That notification is not a nuisance to be
 * hidden: it is the honest signal that something on this phone is trading.
 *
 * This wraps react-native-background-actions so the rest of the app can call
 * two functions and not care. It degrades to a no-op rather than throwing when
 * the native module is missing (Expo Go, or the web preview), because the
 * engine still works in the foreground there.
 */

import { Platform } from 'react-native';

interface BackgroundServiceModule {
  start(task: (params: unknown) => Promise<void>, options: unknown): Promise<void>;
  stop(): Promise<void>;
  updateNotification(options: { taskDesc: string }): Promise<void>;
  isRunning(): boolean;
}

let service: BackgroundServiceModule | null = null;
try {
  // Not available under Expo Go or react-native-web; absence is expected there.
  service = require('react-native-background-actions').default as BackgroundServiceModule;
} catch {
  service = null;
}

export const foregroundServiceAvailable = service !== null && Platform.OS === 'android';

/** Sleeps forever; the engine's own loop does the work. */
const idle = () =>
  new Promise<void>(() => {
    /* resolved never — the service lives until stop() */
  });

export async function startForegroundService(description: string): Promise<boolean> {
  if (!service || Platform.OS !== 'android') return false;
  if (service.isRunning()) {
    await service.updateNotification({ taskDesc: description });
    return true;
  }
  try {
    await service.start(idle, {
      taskName: 'MY-P1',
      taskTitle: 'MY-P1 is trading',
      taskDesc: description,
      taskIcon: { name: 'ic_launcher', type: 'mipmap' },
      color: '#9B7BEA',
      linkingURI: 'myp1://',
      progressBar: undefined,
    });
    return true;
  } catch {
    return false;
  }
}

export async function updateForegroundService(description: string): Promise<void> {
  if (!service || !service.isRunning()) return;
  try {
    await service.updateNotification({ taskDesc: description });
  } catch {
    // A failed notification update must never disturb the trading loop.
  }
}

export async function stopForegroundService(): Promise<void> {
  if (!service) return;
  try {
    if (service.isRunning()) await service.stop();
  } catch {
    // Nothing useful to do; the service dies with the process anyway.
  }
}
