/**
 * Token storage.
 *
 * `expo-secure-store` keeps the token in the iOS keychain / Android keystore.
 * The old apps put it in `AsyncStorage`, which on a rooted or backed-up device
 * is a plain file anyone can read — and a token is a full account.
 */

import * as SecureStore from 'expo-secure-store';

const KEY = 'barbershop.token';

export async function readToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(KEY);
  } catch {
    // A corrupt keystore entry should log the user out, not crash the app on
    // launch.
    return null;
  }
}

export async function writeToken(token: string): Promise<void> {
  try {
    await SecureStore.setItemAsync(KEY, token, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  } catch {
    // Storing failed; the in-memory token still works for this session.
  }
}

export async function clearToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(KEY);
  } catch {
    // Already gone.
  }
}