/**
 * Notification preferences.
 *
 * The old apps had no preference screen at all: every user received every push,
 * forever, with no way to turn any of it off. Some of those pushes are the whole
 * reason someone installs a booking app — a booking confirmation is not the same
 * category as "a new shop opened near you", and treating them the same is how
 * notifications get muted wholesale.
 *
 * Kept on the device for now and synced when the API grows the endpoint; the
 * store is written so that swapping the backing store is a one-file change.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type NotificationKey =
  | 'bookingConfirmations'
  | 'bookingReminders'
  | 'bookingChanges'
  | 'offersAndPromotions'
  | 'newShopsNearby'
  | 'productNews';

export const NOTIFICATION_CATALOGUE: {
  key: NotificationKey;
  label: string;
  description: string;
  /** Off by default: nothing may be opted into on the user's behalf. */
  defaultEnabled: boolean;
  /** Cannot be switched off — a booking confirmation is not marketing. */
  required?: boolean;
}[] = [
  {
    key: 'bookingConfirmations',
    label: 'Booking confirmations',
    description: 'When a booking is confirmed, cancelled or moved.',
    defaultEnabled: true,
    required: true,
  },
  {
    key: 'bookingReminders',
    label: 'Reminders',
    description: 'A nudge before an appointment, and one on the morning of.',
    defaultEnabled: true,
  },
  {
    key: 'bookingChanges',
    label: 'Requests and messages',
    description: 'When a shop accepts, declines or asks you something.',
    defaultEnabled: true,
  },
  {
    key: 'offersAndPromotions',
    label: 'Offers and promotions',
    description: 'Discounts from shops you have used.',
    defaultEnabled: false,
  },
  {
    key: 'newShopsNearby',
    label: 'New shops near you',
    description: 'When something opens in your area.',
    defaultEnabled: false,
  },
  {
    key: 'productNews',
    label: 'Product news',
    description: 'Occasional news about BarberShop itself.',
    defaultEnabled: false,
  },
];

export type NotificationPreferences = Record<NotificationKey, boolean>;

const DEFAULTS = Object.fromEntries(
  NOTIFICATION_CATALOGUE.map(({ key, defaultEnabled }) => [key, defaultEnabled]),
) as NotificationPreferences;

interface NotificationState {
  preferences: NotificationPreferences;
  hydrated: boolean;
  isEnabled: (key: NotificationKey) => boolean;
  set: (key: NotificationKey, enabled: boolean) => void;
  hydrate: () => Promise<void>;
}

export const useNotificationPreferencesStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      preferences: DEFAULTS,
      hydrated: false,

      isEnabled: (key) => {
        // Default to on for anything the store has not seen, so a partial or
        // corrupted store cannot silently mute a confirmation.
        return get().preferences[key] ?? DEFAULTS[key] ?? true;
      },

      set: (key, enabled) => {
        const entry = NOTIFICATION_CATALOGUE.find((item) => item.key === key);
        if (entry?.required && !enabled) return;
        set((state) => ({
          preferences: { ...state.preferences, [key]: enabled },
        }));
      },

      async hydrate() {
        set({ hydrated: true });
      },
    }),
    {
      name: '@barbershop/notifications',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ preferences: state.preferences }),
      onRehydrateStorage: () => (state) => {
        state?.hydrate();
      },
    },
  ),
);

/** Read a preference outside React — used by the push registration helper. */
export function notificationEnabled(key: NotificationKey): boolean {
  return useNotificationPreferencesStore.getState().isEnabled(key);
}