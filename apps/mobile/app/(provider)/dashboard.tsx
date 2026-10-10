import { useMemo } from 'react';
import { RefreshControl, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useBookings, useMyShop } from '@/api/hooks';
import { Button, Card, Divider, useColors } from '@/components/ui';
import { Stat } from '@/components/stat';

export default function ProviderDashboard() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const shop = useMyShop();
  const bookings = useBookings({ upcoming: true });

  const today = useMemo(() => bookings.data?.results ?? [], [bookings.data]);

  const revenue = today
    .filter((booking) => booking.is_paid)
    .reduce((sum, booking) => sum + booking.total, 0);

  const pending = today.filter(
    (booking) => booking.status === 'awaiting_confirmation',
  ).length;

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 8,
          paddingBottom: insets.bottom + 24,
          paddingHorizontal: 16,
          gap: 16,
        }}
        refreshControl={
          <RefreshControl
            refreshing={bookings.isRefetching}
            onRefresh={() => void bookings.refetch()}
            tintColor={colors.accent}
          />
        }>
        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            {shop.data?.display_name ?? 'Your shop'}
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {today.length} upcoming {today.length === 1 ? 'booking' : 'bookings'}
            {pending > 0 ? ` · ${pending} waiting on you` : ''}
          </Text>
        </View>

        <View className="flex-row gap-3">
          <Stat label="Upcoming" value={String(today.length)} />
          <Stat label="Collected" value={`₹${(revenue / 100).toFixed(0)}`} />
          <Stat
            label="Rating"
            value={Number(shop.data?.rating_average ?? 0).toFixed(1)}
          />
        </View>

        {shop.data && !shop.data.is_accepting_bookings ? (
          <Card>
            <View className="gap-2">
              <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                You are not taking bookings
              </Text>
              <Text className="text-xs" style={{ color: colors.textMuted }}>
                Customers can still find you, but they cannot book. Turn it back on
                from your shop settings when you are ready.
              </Text>
              <Button
                variant="secondary"
                onPress={() => router.push('/(provider)/settings')}>
                Open shop settings
              </Button>
            </View>
          </Card>
        ) : null}

        <View className="gap-2">
          <Text className="text-lg font-semibold" style={{ color: colors.text }}>
            Next up
          </Text>

          {bookings.isError ? (
            <Card>
              <Text className="text-sm" style={{ color: colors.danger }}>
                {errorMessage(bookings.error)}
              </Text>
            </Card>
          ) : today.length === 0 ? (
            <Card>
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                Nothing booked yet. Make sure your menu has services and your
                hours are right — customers can only book what they can see.
              </Text>
            </Card>
          ) : (
            <Card>
              {today.slice(0, 4).map((booking, index) => (
                <View key={booking.reference}>
                  {index > 0 ? <Divider className="my-3" /> : null}
                  <View className="flex-row items-center justify-between gap-3">
                    <View className="flex-1">
                      <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                        {booking.customer.display_name}
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textMuted }}>
                        {new Date(booking.starts_at).toLocaleString(undefined, {
                          weekday: 'short',
                          hour: 'numeric',
                          minute: '2-digit',
                        })}{' '}
                        · {booking.items.map((item) => item.name).join(', ')}
                      </Text>
                    </View>
                    <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                      {booking.total_display}
                    </Text>
                  </View>
                </View>
              ))}
            </Card>
          )}
        </View>
      </ScrollView>
    </View>
  );
}