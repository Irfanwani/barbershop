import { Stack } from 'expo-router';

import { useColors } from '@/components/ui';

/**
 * The signed-out stack.
 *
 * `welcome` is only ever the first screen; everything else is reached from it or
 * from the header back button.
 */
export default function AuthLayout() {
  const colors = useColors();

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
        animation: 'slide_from_right',
      }}>
      <Stack.Screen name="welcome" />
      <Stack.Screen name="login" />
      <Stack.Screen name="register" />
      <Stack.Screen name="verify-email" />
      <Stack.Screen name="forgot-password" />
    </Stack>
  );
}