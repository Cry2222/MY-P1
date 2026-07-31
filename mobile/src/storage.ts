/**
 * Connection persistence.
 *
 * The API token can halt trading, so it goes in the device keystore
 * (expo-secure-store: Keychain on iOS, EncryptedSharedPreferences on Android),
 * never in AsyncStorage. The server address is not a secret and lives beside
 * it only for convenience.
 *
 * On web, SecureStore is unavailable and this falls back to localStorage —
 * acceptable for the dev preview, which is why the app warns when it happens.
 */

import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type { Connection } from './api/types';

const URL_KEY = 'myp1.baseUrl';
const TOKEN_KEY = 'myp1.token';

const webStore = {
  getItem: (key: string) =>
    typeof localStorage === 'undefined' ? null : localStorage.getItem(key),
  setItem: (key: string, value: string) => {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
  },
  removeItem: (key: string) => {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(key);
  },
};

export const isSecureStorageAvailable = Platform.OS !== 'web';

async function read(key: string): Promise<string | null> {
  if (!isSecureStorageAvailable) return webStore.getItem(key);
  try {
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

async function write(key: string, value: string): Promise<void> {
  if (!isSecureStorageAvailable) {
    webStore.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function remove(key: string): Promise<void> {
  if (!isSecureStorageAvailable) {
    webStore.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export async function loadConnection(): Promise<Connection | null> {
  const [baseUrl, token] = await Promise.all([read(URL_KEY), read(TOKEN_KEY)]);
  if (!baseUrl || !token) return null;
  return { baseUrl, token };
}

export async function saveConnection(connection: Connection): Promise<void> {
  await Promise.all([
    write(URL_KEY, connection.baseUrl),
    write(TOKEN_KEY, connection.token),
  ]);
}

export async function clearConnection(): Promise<void> {
  await Promise.all([remove(URL_KEY), remove(TOKEN_KEY)]);
}
