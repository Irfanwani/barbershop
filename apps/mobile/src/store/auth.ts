/**
 * Where the signed-in account lives.
 *
 * Zustand rather than Redux: the state is one object with a handful of actions,
 * and there is no dispatch/reducer/action-type ceremony to keep in step. Server
 * data stays in TanStack Query; this store owns only what is true on this
 * device — who is signed in, and what they are allowed to see.
 */

import { create } from 'zustand';

import { api, isApiError } from '@/api/client';
import { clearToken, readToken, writeToken } from '@/lib/secure-store';
import type { Role, User } from '@/types/api';

export type AuthStatus = 'loading' | 'signed-out' | 'signed-in';

interface AuthState {
  status: AuthStatus;
  token: string | null;
  user: User | null;
  /** Why the last request failed, if it did. Shown on the launch screen. */
  error: string | null;

  bootstrap: () => Promise<void>;
  setSession: (token: string, user: User) => Promise<void>;
  setUser: (user: User) => void;
  signOut: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'loading',
  token: null,
  user: null,
  error: null,

  async bootstrap() {
    const token = await readToken();
    if (!token) {
      set({ status: 'signed-out', token: null, user: null });
      return;
    }

    // The token survives an app restart; the account may not. Confirming with
    // /me/ is the difference between opening the app signed in and opening it
    // on a screen that quietly 401s on every request.
    set({ token });
    try {
      const user = await api.get<User>('/me/');
      set({ status: 'signed-in', user, error: null });
    } catch (error) {
      if (isApiError(error) && error.isUnauthorized) {
        await clearToken();
        set({ status: 'signed-out', token: null, user: null, error: null });
      } else {
        // A network blip must not sign anyone out: that would throw away
        // whatever they had typed. Keep the token and let them retry.
        set({
          status: 'signed-out',
          token,
          user: null,
          error: isApiError(error) ? error.message : 'Could not reach the server.',
        });
      }
    }
  },

  async setSession(token, user) {
    await writeToken(token);
    set({ status: 'signed-in', token, user, error: null });
  },

  setUser(user) {
    set({ user });
  },

  async signOut() {
    await clearToken();
    set({ status: 'signed-out', token: null, user: null, error: null });
  },

  clearError() {
    set({ error: null });
  },
}));

/** The role, or null when signed out. Read in layouts to pick a navigator. */
export function useRole(): Role | null {
  return useAuthStore((state) => state.user?.role ?? null);
}

/** Synchronous token read, for the HTTP client. */
export function currentToken(): string | null {
  return useAuthStore.getState().token;
}