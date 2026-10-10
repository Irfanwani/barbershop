import { useMemo, useState } from 'react';
import { Image, Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useAvailability, useCustomerProfile, useProvider, useReviews } from '@/api/hooks';
import { Badge, Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { ReviewList } from '@/components/review-list';
import { BookingSheet } from '@/components/booking-sheet';
import { formatRelative } from '@/components/booking-row';

export default function ProviderDetailScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();

  const providerId = Number(id);
  const { data: profile } = useCustomerProfile();

  const origin = useMemo(
    () => (profile?.coords ? { lat: profile.coords.latitude, lng: profile.coords.longitude } : undefined),
    [profile?.coords],
  );

  const provider = useProvider(Number.isFinite(providerId) ? providerId : null, origin);
  const reviews = useReviews({ provider: providerId });
  const availability = useAvailability(Number.isFinite(providerId) ? providerId : null, 7);

  const [booking, setBooking] = useState(false);

  if (provider.isLoading) {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: colors.background }}>
        <Text style={{ color: colors.textMuted }}>Loading…</Text>
      </View>
    );
  }

  if (provider.isError || !provider.data) {
    return (
      <EmptyState
        icon="alert-circle-outline"
        title="Could not load this shop"
        body={errorMessage(provider.error)}
        action={<Button variant="secondary" onPress={() => void provider.refetch()}>Try again</Button>}
      />
    );
  }

  const shop = provider.data;
  const services = shop.services.filter((service) => service.is_active);
  const canBook = shop.accepts_bookings && services.length > 0;

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: insets.bottom + 96 }}>
        <View className="relative">
          {shop.cover_photo ?? shop.photo ? (
            <Image
              source={{ uri: (shop.cover_photo ?? shop.photo) as string }}
              style={{ width: '100%', height: 220 }}
              resizeMode="cover"
              accessibilityIgnoresInvertColors
            />
          ) : (
            <View style={{ height: 160, backgroundColor: colors.surface }} />
          )}

          <View className="absolute left-3 top-3">
            <IconButton
              name="arrow-back"
              label="Back"
              onPress={() => router.back()}
              color="#FFFFFF"
              className="bg-black/40"
            />
          </View>
        </View>

        <View className="-mt-6 gap-4 px-4">
          <View
            className="gap-3 rounded-3xl p-5"
            style={{ backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1 }}>
            <View className="gap-1">
              <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
                {shop.display_name}
              </Text>
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                {shop.service_type_label} · {shop.address}
              </Text>
            </View>

            <View className="flex-row items-center gap-4">
              <View className="flex-row items-center gap-1">
                <Ionicons name="star" size={15} color="#F59E0B" />
                <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                  {Number(shop.rating_average || 0).toFixed(1)}
                </Text>
                <Text className="text-xs" style={{ color: colors.textSubtle }}>
                  ({shop.rating_count})
                </Text>
              </View>
              {shop.distance_km !== undefined ? (
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {shop.distance_km} km away
                </Text>
              ) : null}
              {shop.is_open_now ? <Badge tone="success">Open now</Badge> : <Badge tone="danger">Closed</Badge>}
            </View>

            <View className="flex-row items-center gap-2">
              <Ionicons name="time-outline" size={15} color={colors.textMuted} />
              <Text className="text-sm">
                {formatClock(shop.opening_time)} – {formatClock(shop.closing_time)}
              </Text>
              {shop.next_available ? (
                <Text className="text-sm" style={{ color: colors.success }}>
                  · next free {formatRelative(shop.next_available)}
                </Text>
              ) : null}
            </View>
          </View>

          {shop.description ? (
            <Text className="px-1 text-[15px] leading-6" style={{ color: colors.textMuted }}>
              {shop.description}
            </Text>
          ) : null}

          <View className="gap-3">
            <Text className="text-lg font-semibold" style={{ color: colors.text }}>
              Menu
            </Text>
            {services.length === 0 ? (
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                This shop has not published a menu yet.
              </Text>
            ) : (
              <Card>
                {services.map((service, index) => (
                  <View key={service.id}>
                    {index > 0 ? <Divider className="my-3" /> : null}
                    <View className="flex-row items-center justify-between gap-3">
                      <View className="flex-1">
                        <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                          {service.name}
                        </Text>
                        <Text className="text-xs" style={{ color: colors.textSubtle }}>
                          {service.duration_minutes} min
                        </Text>
                      </View>
                      <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
                        {service.price_display}
                      </Text>
                    </View>
                  </View>
                ))}
              </Card>
            )}
          </View>

          <View className="gap-3">
            <Text className="text-lg font-semibold" style={{ color: colors.text }}>
              Reviews
            </Text>
            <ReviewList
              reviews={reviews.data?.results ?? []}
              summary={reviews.data?.summary}
              loading={reviews.isLoading}
            />
          </View>
        </View>
      </ScrollView>

      <View
        className="absolute inset-x-0 bottom-0 border-t px-4 py-3"
        style={{ backgroundColor: colors.surface, borderTopColor: colors.border, paddingBottom: insets.bottom + 12 }}>
        <Button
          onPress={() => setBooking(true)}
          disabled={!canBook}
          testID="provider-book">
          {canBook
            ? `Book · from ${shop.starting_price_display ?? ''}`
            : shop.services.length === 0
              ? 'No services yet'
              : 'Not taking bookings'}
        </Button>
      </View>

      <BookingSheet
        visible={booking}
        onClose={() => setBooking(false)}
        provider={shop}
        availability={availability.data}
      />
    </View>
  );
}

/** "09:00:00" -> "9:00 AM". The API speaks ISO; humans do not. */
function formatClock(value: string): string {
  const [hours, minutes] = value.split(':');
  const hour = Number(hours);
  const suffix = hour >= 12 ? 'PM' : 'AM';
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}:${minutes} ${suffix}`;
}

export { Pressable };