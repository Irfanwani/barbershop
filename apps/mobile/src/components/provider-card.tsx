import { Image, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { Card, useColors } from '@/components/ui';
import type { ProviderListItem } from '@/types/api';

/**
 * One shop in the browse list.
 *
 * The order of what is on the card is deliberate: what it is, how close it is,
 * what people say, what it costs. Distance is in the top corner because it is
 * the reason the list is sorted the way it is.
 */
export function ProviderCard({
  provider,
  onPress,
}: {
  provider: ProviderListItem;
  onPress: () => void;
}) {
  const colors = useColors();
  const closed = !provider.is_open_now;

  return (
    <Card onPress={onPress} className="gap-3">
      <View className="flex-row gap-3">
        {provider.photo ? (
          <Image
            source={{ uri: provider.photo }}
            style={{ width: 72, height: 72, borderRadius: 16 }}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View
            className="h-[72px] w-[72px] items-center justify-center rounded-2xl"
            style={{ backgroundColor: colors.surface }}>
            <Ionicons name="cut-outline" size={26} color={colors.textSubtle} />
          </View>
        )}

        <View className="flex-1 gap-1">
          <View className="flex-row items-start justify-between gap-2">
            <Text
              numberOfLines={1}
              className="flex-1 text-base font-semibold"
              style={{ color: colors.text }}>
              {provider.display_name}
            </Text>
            {provider.distance_km !== undefined ? (
              <Text className="text-xs font-semibold" style={{ color: colors.accent }}>
                {provider.distance_km < 1
                  ? `${Math.round(provider.distance_km * 1000)} m`
                  : `${provider.distance_km} km`}
              </Text>
            ) : null}
          </View>

          <Text numberOfLines={1} className="text-xs" style={{ color: colors.textMuted }}>
            {provider.service_type_label} · {provider.address}
          </Text>

          <View className="mt-0.5 flex-row items-center gap-2">
            <Ionicons name="star" size={13} color="#F59E0B" />
            <Text className="text-xs font-medium" style={{ color: colors.text }}>
              {Number(provider.rating_average || 0).toFixed(1)}
            </Text>
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              ({provider.rating_count})
            </Text>
            {provider.starting_price_display ? (
              <Text className="text-xs" style={{ color: colors.textSubtle }}>
                · from {provider.starting_price_display}
              </Text>
            ) : null}
          </View>
        </View>
      </View>

      <View className="flex-row items-center gap-2">
        <View
          className="flex-row items-center gap-1 rounded-full px-2 py-1"
          style={{ backgroundColor: closed ? `${colors.danger}14` : `${colors.success}14` }}>
          <Ionicons
            name={closed ? 'moon-outline' : 'sunny-outline'}
            size={11}
            color={closed ? colors.danger : colors.success}
          />
          <Text
            className="text-2xs font-semibold"
            style={{ color: closed ? colors.danger : colors.success }}>
            {closed ? 'Closed now' : 'Open now'}
          </Text>
        </View>

        {provider.requires_approval ? (
          <View
            className="rounded-full px-2 py-1"
            style={{ backgroundColor: colors.surfaceRaised }}>
            <Text className="text-2xs font-semibold" style={{ color: colors.textMuted }}>
              Approval needed
            </Text>
          </View>
        ) : null}
      </View>
    </Card>
  );
}