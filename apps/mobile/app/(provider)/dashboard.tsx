import { useMemo, useState } from 'react';
import { RefreshControl, ScrollView, Text, TouchableOpacity, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useBookings, useMyShop, useProviderAnalytics } from '@/api/hooks';
import { Button, Card, Divider, useColors } from '@/components/ui';
import { Stat } from '@/components/stat';

const WINDOWS = [7, 30, 90] as const;

export default function ProviderDashboard() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [days, setDays] = useState<number>(30);
  const shop = useMyShop();
  const bookings = useBookings({ upcoming: true });
  const analytics = useProviderAnalytics(days);

  const upcoming = useMemo(() => bookings.data?.results ?? [], [bookings.data]);
  const now = analytics.data?.current;

  // The one thing still worth counting on the device: what is waiting on the
  // provider to act. That is a list of bookings the app has already loaded,
  // not a number that has to be right across every page.
  const pending = useMemo(
    () => upcoming.filter((booking) => booking.status === 'awaiting_confirmation').length,
    [upcoming],
  );

  const change = analytics.data?.changes.revenue_earned;
  const trend = change?.percent ?? null;

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
            refreshing={analytics.isRefetching}
            onRefresh={() => void analytics.refetch()}
            tintColor={colors.accent}
          />
        }>
        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            {shop.data?.display_name ?? 'Your shop'}
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {upcoming.length} upcoming {upcoming.length === 1 ? 'booking' : 'bookings'}
            {pending > 0 ? ` · ${pending} waiting on you` : ''}
          </Text>
        </View>

        <View className="flex-row gap-3">
          <Stat label="Upcoming" value={String(upcoming.length)} />
          <Stat label={`Earned, ${days}d`} value={now?.revenue_earned_display ?? '—'} />
          <Stat label="Rating" value={Number(shop.data?.rating_average ?? 0).toFixed(1)} />
        </View>

        <View className="gap-3">
          <View className="flex-row gap-2">
            {WINDOWS.map((window_) => (
              <TouchableOpacity
                key={window_}
                onPress={() => setDays(window_)}
                className="rounded-full px-3 py-1"
                style={{
                  backgroundColor: days === window_ ? colors.accent : colors.surface,
                }}>
                <Text
                  className="text-xs font-medium"
                  style={{ color: days === window_ ? colors.accentText : colors.textMuted }}>
                  {window_}d
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {analytics.isError ? (
            <Card>
              <Text className="text-sm" style={{ color: colors.danger }}>
                {errorMessage(analytics.error)}
              </Text>
            </Card>
          ) : !now ? (
            <Card>
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                Loading your numbers…
              </Text>
            </Card>
          ) : (
            <>
              <Card>
                <View className="gap-1">
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    You kept {now.revenue_earned_display} over {days} days
                  </Text>
                  {trend === null ? (
                    <Text className="text-sm" style={{ color: colors.textMuted }}>
                      {change?.before === 0
                        ? 'Nothing earned in the {days} days before, so there is no percentage to compare.'
                        : 'Compared with the previous {days} days.'}
                    </Text>
                  ) : (
                    <Text
                      className="text-sm"
                      style={{ color: trend >= 0 ? colors.success : colors.danger }}>
                      {trend >= 0 ? '▲' : '▼'}{' '}
                      {Math.abs(trend).toFixed(0)}% on the previous {days} days
                    </Text>
                  )}
                  {now.tips > 0 ? (
                    <Text className="text-xs" style={{ color: colors.textMuted }}>
                      Including {now.tips_display} in tips.
                    </Text>
                  ) : null}
                </View>
              </Card>

              <View className="flex-row gap-3">
                <Stat label="Completed" value={String(now.completed)} />
                <Stat
                  label="Returning"
                  value={
                    now.eligible_customers > 0
                      ? `${Math.round(now.rebooking_rate * 100)}%`
                      : '—'
                  }
                />
                <Stat label="No-shows" value={`${Math.round(now.no_show_rate * 100)}%`} />
              </View>

              {now.per_service.length > 0 ? (
                <Card>
                  <Text className="text-base font-semibold" style={{ color: colors.text }}>
                    What earns
                  </Text>
                  {now.per_service.map((row, index) => (
                    <View key={row.name}>
                      {index > 0 ? <Divider className="my-3" /> : null}
                      <View className="flex-row items-center justify-between gap-3">
                        <Text className="text-sm" style={{ color: colors.text }}>
                          {row.name}
                        </Text>
                        <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                          {row.earnings_display}
                        </Text>
                      </View>
                    </View>
                  ))}
                </Card>
              ) : null}
            </>
          )}
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
          ) : upcoming.length === 0 ? (
            <Card>
              <Text className="text-sm" style={{ color: colors.textMuted }}>
                Nothing booked yet. Make sure your menu has services and your
                hours are right — customers can only book what they can see.
              </Text>
            </Card>
          ) : (
            <Card>
              {upcoming.slice(0, 4).map((booking, index) => (
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