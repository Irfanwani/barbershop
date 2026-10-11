import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import {
  useCustomerProfile,
  usePriceBands,
  useProviderSearch,
  useServiceTypes,
} from '@/api/hooks';
import { Badge, Button, Card, EmptyState, useColors } from '@/components/ui';
import { ProviderCard } from '@/components/provider-card';
import { SearchFilters, type Filters } from '@/components/search-filters';
import { useAuthStore } from '@/store/auth';

export default function CustomerHome() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const displayName = useAuthStore((state) => state.user?.display_name ?? '');

  const { data: profile } = useCustomerProfile();
  const { data: types } = useServiceTypes();

  const [filters, setFilters] = useState<Filters>({
    serviceType: 'all',
    services: [],
    openNow: false,
    minRating: 0,
  });
  const [refreshing, setRefreshing] = useState(false);

  const origin = useMemo(
    () => (profile?.coords ? { lat: profile.coords.latitude, lng: profile.coords.longitude } : undefined),
    [profile?.coords],
  );

  const search = useProviderSearch({
    ...(origin ?? {}),
    service_type: filters.serviceType && filters.serviceType !== 'all' ? filters.serviceType : undefined,
    services: filters.services,
    open_now: filters.openNow || undefined,
    min_rating: filters.minRating || undefined,
    page_size: 20,
  });

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await search.refetch();
    setRefreshing(false);
  }, [search]);

  const providers = search.data?.results ?? [];

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <FlatList
        data={providers}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{
          paddingTop: insets.top + 8,
          paddingBottom: insets.bottom + 24,
          gap: 12,
        }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        ListHeaderComponent={
          <View className="gap-4 px-4 pb-2">
            <View className="gap-1">
              <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
                {greeting(displayName)}
              </Text>
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                {origin
                  ? `${search.data?.count ?? 0} shops near you`
                  : 'Add a location to sort shops by distance'}
              </Text>
            </View>

            {!origin ? (
              <Card>
                <View className="gap-3">
                  <Text className="text-sm" style={{ color: colors.text }}>
                    We do not know where you are yet, so these are not sorted by
                    distance.
                  </Text>
                  <Button
                    variant="secondary"
                    onPress={() => router.push('/(onboarding)/customer-location')}>
                    Set my location
                  </Button>
                </View>
              </Card>
            ) : null}

            <SearchFilters
              value={filters}
              onChange={setFilters}
              serviceTypes={types ?? []}
            />

            <PriceHint />
          </View>
        }
        renderItem={({ item }) => (
          <View className="px-4">
            <ProviderCard
              provider={item}
              onPress={() => router.push(`/(customer)/provider/${item.id}`)}
            />
          </View>
        )}
        ListEmptyComponent={
          search.isLoading ? null : search.isError ? (
            <EmptyState
              icon="cloud-offline-outline"
              title="Could not load shops"
              body={errorMessage(search.error)}
              action={<Button variant="secondary" onPress={() => void search.refetch()}>Try again</Button>}
            />
          ) : (
            <EmptyState
              icon="search-outline"
              title="Nothing matches those filters"
              body="Try widening the distance or clearing a filter or two."
              action={
                <Badge tone="accent">Filters are remembered</Badge>
              }
            />
          )
        }
      />
    </View>
  );
}

function greeting(name: string): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Morning' : hour < 17 ? 'Afternoon' : 'Evening';
  return name ? `${part}, ${name.split(' ')[0]}` : part;
}

/**
 * What this kind of shop usually charges, above the results.
 *
 * A customer scrolling shops is comparing prices while they scroll. Putting
 * the typical figure next to the list answers the question they have not yet
 * thought to ask, and a thin sample says so rather than asserting a rate.
 */
function PriceHint() {
  const colors = useColors();
  const router = useRouter();
  const bands = usePriceBands();

  const band = bands.data?.bands.find((entry) => entry.sample_size > 0);
  if (!band?.median_display) return null;

  return (
    <Pressable
      onPress={() => router.push('/prices')}
      accessibilityRole="button"
      accessibilityLabel="See what shops usually charge"
      className="flex-row items-center gap-2 rounded-2xl border px-3 py-2.5 active:opacity-70"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
      <Ionicons name="pricetag-outline" size={16} color={colors.accent} />
      <Text className="flex-1 text-xs" style={{ color: colors.textMuted }}>
        {band.is_thin
          ? `${band.service_type_label} prices here start around ${band.minimum_display}`
          : `${band.service_type_label} here typically cost ${band.median_display}`}
      </Text>
      <Ionicons name="chevron-forward" size={14} color={colors.textSubtle} />
    </Pressable>
  );
}
