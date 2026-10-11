import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePriceBands, useServicePrices } from '@/api/hooks';
import { Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { Stat } from '@/components/stat';

/**
 * What things usually cost.
 *
 * Shown to someone who has not picked a shop yet, which is exactly when the
 * number is useful and exactly when a wrong one is costly. Every figure is
 * labelled with how many shops it came from, and a thin one says so — "most
 * barbers here charge about ₹50" when one barbershop exists is worse than no
 * answer at all.
 */
export default function PricesScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const bands = usePriceBands();
  const services = useServicePrices();

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
      <IconButton
        name="arrow-back"
        label="Back"
        onPress={() => router.back()}
        className="self-start"
      />

      <View className="gap-1">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Prices
        </Text>
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          What shops on BarberShop are charging, from the prices they actually list.
        </Text>
      </View>

      {bands.isLoading || services.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Working out what things cost…
        </Text>
      ) : (bands.data?.bands.length ?? 0) === 0 && (services.data?.services.length ?? 0) === 0 ? (
        <EmptyState
          icon="pricetag-outline"
          title="Not enough prices yet"
          body="Once a few shops list prices, the usual range shows up here."
        />
      ) : null}

      {services.data?.services.length ? (
        <View className="gap-2">
          <Text
            className="px-1 text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.textSubtle }}>
            By service
          </Text>
          {services.data.services.map((entry) => (
            <Card key={entry.name} className="gap-1.5">
              <View className="flex-row items-center justify-between gap-3">
                <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
                  {entry.name}
                </Text>
                <Text className="text-base font-bold" style={{ color: colors.text }}>
                  {entry.median_display ?? '—'}
                </Text>
              </View>
              <Text className="text-xs" style={{ color: colors.textSubtle }}>
                Most shops charge {entry.minimum_display} to {entry.maximum_display} · from{' '}
                {entry.sample_size} shops
              </Text>
            </Card>
          ))}
        </View>
      ) : null}

      {bands.data?.bands.length ? (
        <View className="gap-2">
          <Text
            className="px-1 text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.textSubtle }}>
            By shop type
          </Text>
          {bands.data.bands.map((band) => (
            <Card key={band.service_type} className="gap-3">
              <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
                {band.service_type_label}
              </Text>

              <View className="flex-row gap-3">
                <View className="flex-1">
                  <Stat label="Typical" value={band.median_display ?? '—'} />
                </View>
                <View className="flex-1">
                  <Stat label="Lowest" value={band.minimum_display ?? '—'} />
                </View>
                <View className="flex-1">
                  <Stat label="Highest" value={band.maximum_display ?? '—'} />
                </View>
              </View>

              {band.is_thin ? (
                <View
                  className="flex-row items-start gap-2 rounded-xl px-3 py-2"
                  style={{ backgroundColor: `${colors.warning}14` }}>
                  <Ionicons name="information-circle-outline" size={16} color={colors.warning} />
                  <Text className="flex-1 text-xs" style={{ color: colors.warning }}>
                    Based on {band.sample_size}{' '}
                    {band.sample_size === 1 ? 'shop' : 'shops'} only. Treat this as a rough
                    guide, not a going rate.
                  </Text>
                </View>
              ) : (
                <Text className="text-xs" style={{ color: colors.textSubtle }}>
                  Most shops fall between {band.p25_display} and {band.p75_display} · from{' '}
                  {band.sample_size} shops
                </Text>
              )}
            </Card>
          ))}
        </View>
      ) : null}

      <Card className="gap-1">
        <Text className="text-sm font-semibold" style={{ color: colors.text }}>
          How this is worked out
        </Text>
        <Divider className="my-2" />
        <Text className="text-xs leading-5" style={{ color: colors.textMuted }}>
          Every price a provider lists counts, except ones outside a sensible range for a
          haircut — a ₹1 or ₹50,000 entry is a mistake, not a price, and would drag the figure
          away from anything real. Shops that only offer one service, or none, are not counted.
        </Text>
      </Card>
    </ScrollView>
  );
}