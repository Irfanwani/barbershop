import { Stack } from 'expo-router';

import { useColors } from '@/components/ui';

/**
 * Onboarding: the short set-up a new account has to get through before it is
 * useful. A customer needs a location so "near me" works; a provider needs a
 * shop, an address, hours and at least one service on the menu.
 */
export default function OnboardingLayout() {
  const colors = useColors();

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
        animation: 'slide_from_right',
      }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="customer-location" />
      <Stack.Screen name="provider-details" />
      <Stack.Screen name="provider-services" />
    </Stack>
  );
}