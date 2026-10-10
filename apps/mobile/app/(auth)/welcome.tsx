import { Image, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, useColors } from '@/components/ui';

const HIGHLIGHTS = [
  {
    icon: 'location-outline' as const,
    title: 'Shops near you, ranked',
    body: 'Sorted by real distance, with today’s openings and prices on the card.',
  },
  {
    icon: 'calendar-outline' as const,
    title: 'Booked in three taps',
    body: 'Pick a slot, see the price before you pay, and it is in your calendar.',
  },
  {
    icon: 'cut-outline' as const,
    title: 'For the people who cut',
    body: 'Run your whole shop from the same app: bookings, menu, payouts.',
  },
];

export default function WelcomeScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 24,
          paddingBottom: insets.bottom + 24,
          paddingHorizontal: 24,
          gap: 28,
        }}
        showsVerticalScrollIndicator={false}>
        <View className="items-center gap-4">
          <Image
            source={require('@/assets/icon.png')}
            style={{ width: 96, height: 96, borderRadius: 24 }}
            accessibilityLabel="BarberShop"
            resizeMode="cover"
          />
          <Text
            className="text-center text-4xl font-bold tracking-tight"
            style={{ color: colors.text }}>
            BarberShop
          </Text>
          <Text
            className="text-center text-base leading-6"
            style={{ color: colors.textMuted }}>
            Every barber, salon and spa near you — and the tools to run one, if
            that is you.
          </Text>
        </View>

        <View className="gap-4">
          {HIGHLIGHTS.map((highlight) => (
            <View key={highlight.title} className="flex-row items-start gap-3">
              <View
                className="h-10 w-10 items-center justify-center rounded-xl"
                style={{ backgroundColor: `${colors.accent}1a` }}>
                <Ionicons name={highlight.icon} size={20} color={colors.accent} />
              </View>
              <View className="flex-1 gap-1">
                <Text className="text-base font-semibold" style={{ color: colors.text }}>
                  {highlight.title}
                </Text>
                <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
                  {highlight.body}
                </Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      <View
        className="gap-3 px-6 pb-8"
        style={{ paddingBottom: insets.bottom + 24 }}>
        <Button testID="welcome-get-started" onPress={() => router.push('/(auth)/register')}>
          Get started
        </Button>
        <Button variant="ghost" onPress={() => router.push('/(auth)/login')}>
          I already have an account
        </Button>
      </View>
    </View>
  );
}