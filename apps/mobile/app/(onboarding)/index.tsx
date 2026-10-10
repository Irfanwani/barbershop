import { Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { Button, useColors } from '@/components/ui';
import { useAuthStore } from '@/store/auth';

/**
 * Sends a new account to the right first step.
 *
 * A customer is asked where they are, because every provider search starts from
 * somewhere. A provider is asked about the shop, because a shop with no address
 * cannot be booked.
 */
export default function OnboardingIndex() {
  const colors = useColors();
  const router = useRouter();
  const role = useAuthStore((state) => state.user?.role);

  return (
    <View
      className="flex-1 justify-between px-6 py-10"
      style={{ backgroundColor: colors.background }}>
      <View className="gap-3">
        <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
          {role === 'provider' ? 'Tell us about your shop' : 'Where should we look?'}
        </Text>
        <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
          {role === 'provider'
            ? 'A few details and your shop is bookable. You can change any of this later.'
            : 'We use your location to show shops near you. You can change it whenever.'}
        </Text>
      </View>

      <View className="gap-3">
        <Button
          testID="onboarding-continue"
          onPress={() =>
            router.replace(
              role === 'provider' ? '/(onboarding)/provider-details' : '/(onboarding)/customer-location',
            )
          }>
          Continue
        </Button>
      </View>
    </View>
  );
}