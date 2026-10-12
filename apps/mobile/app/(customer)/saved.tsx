import { useState } from 'react';
import { Image, Pressable, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useSavedShops, useToggleSavedShop } from '@/api/hooks';
import { Button, Card, EmptyState, IconButton, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import { formatPaise, isShopPaused } from '@/lib/money';
import type { SavedShop } from '@/types/api';

/**
 * Saved shops.
 *
 * A paused shop stays in this list, greyed. Somebody's usual barber does not
 * stop existing because they took a holiday, and hiding it would make a saved
 * list look broken at exactly the moment somebody wants it.
 *
 * Prices are the shop's *current* ones, not the ones they saved it at.
 * Showing a stale price would make this worse than not offering the feature.
 */
export default function SavedScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const saved = useSavedShops();
  const toggle = useToggleSavedShop();
  const [error, setError] = useState<string | null>(null);

  async function unsave(shop: SavedShop) {
    setError(null);
    try {
      await toggle.mutateAsync({ providerId: shop.provider.id, saved: true });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not remove that shop.'));
    }
  }

  const shops = saved.data ?? [];

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}
      keyboardShouldPersistTaps="handled">
      <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

      <View className="gap-1">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Saved
        </Text>
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          The shops you want to find again. These come first when you browse.
        </Text>
      </View>

      <FormError message={error} />

      {saved.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Loading your shops…
        </Text>
      ) : shops.length === 0 ? (
        <EmptyState
          icon="heart-outline"
          title="Nothing saved yet"
          body="Tap the heart on a shop and it will be here — and first in your list when you come looking again."
        />
      ) : (
        <View className="gap-3">
          {shops.map((entry) => (
            <SavedCard key={entry.id} entry={entry} onRemove={() => unsave(entry)} />
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function SavedCard({ entry, onRemove }: { entry: SavedShop; onRemove: () => void }) {
  const colors = useColors();
  const router = useRouter();
  const shop = entry.provider;
  const paused = isShopPaused(shop);

  const initial = (shop.display_name || '?').trim().charAt(0).toUpperCase();

  return (
    <Pressable
      onPress={() => router.push(`/(customer)/provider/${shop.id}`)}
      accessibilityRole="button"
      testID={`saved-${shop.id}`}>
      <Card className={paused ? 'gap-3 opacity-60' : 'gap-3'}>
        <View className="flex-row items-start justify-between gap-3">
          <View className="flex-1 gap-1">
            <Text className="text-base font-semibold" style={{ color: colors.text }}>
              {shop.display_name}
            </Text>
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              {shop.service_type_label}
              {shop.rating_count ? ` · ${shop.rating_average} from ${shop.rating_count}` : ''}
            </Text>
          </View>

          {shop.photo ? (
            <Image
              source={{ uri: shop.photo }}
              style={{ width: 40, height: 40, borderRadius: 20 }}
            />
          ) : (
            <View
              className="h-10 w-10 items-center justify-center rounded-full"
              style={{ backgroundColor: colors.surfaceRaised }}>
              <Text className="text-sm font-bold" style={{ color: colors.textMuted }}>
                {initial}
              </Text>
            </View>
          )}
        </View>

        {entry.note ? (
          <Text className="text-xs italic" style={{ color: colors.textSubtle }}>
            “{entry.note}”
          </Text>
        ) : null}

        {paused ? (
          <Text className="text-xs font-medium" style={{ color: colors.warning }}>
            Not taking bookings at the moment
          </Text>
        ) : (
          <Text className="text-sm" style={{ color: colors.text }}>
            From {formatPaise(shop.starting_price)}
          </Text>
        )}

        <Button variant="ghost" className="self-start" onPress={onRemove} testID={`unsave-${shop.id}`}>
          Remove
        </Button>
      </Card>
    </Pressable>
  );
}
