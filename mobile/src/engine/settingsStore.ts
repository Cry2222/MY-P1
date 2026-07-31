/**
 * Settings persistence.
 *
 * Settings are not secret, so they live in the journal's control table rather
 * than the keystore — one store, one thing to back up, and they survive an app
 * restart the same way the kill switch does.
 */

import { DEFAULT_SETTINGS, type EngineSettings } from './config';
import type { Journal } from './journal';

const KEY = 'engine_settings';

export async function loadSettings(journal: Journal): Promise<EngineSettings> {
  const stored = await journal.getControl<Partial<EngineSettings> | null>(KEY, null);
  if (!stored) return DEFAULT_SETTINGS;
  // Merge over defaults so a settings file written by an older build does not
  // leave new fields undefined.
  return {
    ...DEFAULT_SETTINGS,
    ...stored,
    risk: { ...DEFAULT_SETTINGS.risk, ...(stored.risk ?? {}) },
  };
}

export async function saveSettings(journal: Journal, settings: EngineSettings): Promise<void> {
  await journal.setControl(KEY, settings);
}
