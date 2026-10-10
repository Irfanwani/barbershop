/**
 * Jest setup.
 *
 * `jest-expo` cannot run `expo-secure-store`, the location APIs or the router's
 * native side, so they are replaced with the smallest thing that lets a test
 * exercise the logic around them. Anything a real screen depends on is stubbed
 * honestly — a mock that behaves differently from the real module is worse than
 * no mock at all.
 */

// @testing-library/react-native v13+ registers its matchers on import.
import '@testing-library/react-native';

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('expo-secure-store', () => {
  const store = new Map<string, string>();
  return {
    getItemAsync: jest.fn(async (key: string) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      store.delete(key);
    }),
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY',
  };
});

jest.mock('expo-location', () => ({
  Accuracy: { Balanced: 3 },
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getForegroundPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getCurrentPositionAsync: jest.fn(async () => ({
    coords: { latitude: 28.6139, longitude: 77.209, accuracy: 10 },
  })),
  reverseGeocodeAsync: jest.fn(async () => [
    { city: 'New Delhi', region: 'Delhi', country: 'India' },
  ]),
}));

jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  requestPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[test]' })),
  setNotificationChannelAsync: jest.fn(async () => undefined),
  AndroidImportance: { HIGH: 4, DEFAULT: 3 },
}));

jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn(async () => undefined),
  notificationAsync: jest.fn(async () => undefined),
  ImpactFeedbackStyle: { Light: 'light', Medium: 'medium' },
  NotificationFeedbackType: { Success: 'success', Error: 'error' },
}));

jest.mock('expo-router', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    navigate: jest.fn(),
    setParams: jest.fn(),
  }),
  useLocalSearchParams: () => ({}),
  useSegments: () => [],
  usePathname: () => '/',
  Redirect: jest.fn(() => null),
  Stack: Object.assign(() => null, { Screen: jest.fn() }),
  Tabs: Object.assign(() => null, { Screen: jest.fn() }),
  Link: jest.fn(() => null),
}));

// Ionicons pulls in expo-font, which needs a native module. A test that asserts
// on an icon's glyph is asserting on a font that is not loaded, so the whole set
// collapses to a host component that renders nothing.
jest.mock('@expo/vector-icons', () => {
  const React = require('react');
  const { Text } = require('react-native');
  // Props are passed through: an icon that is the only tap target on a screen
  // has to stay pressable in a test, or "does this button work" is untestable.
  const Icon = ({ name, ...props }: Record<string, unknown>) =>
    React.createElement(Text, { testID: `icon-${String(name)}`, ...props }, null);
  return new Proxy({}, { get: () => Icon });
});

// NativeWind turns this into a style registry in the real app; in tests the
// class names are all that matter.
jest.mock('react-native-reanimated', () => {
  const Reanimated = require('react-native-reanimated/mock');
  Reanimated.default.call = () => {};
  return Reanimated;
});

beforeEach(() => {
  jest.clearAllMocks();
});
