import { useState } from 'react';
import { FlatList, RefreshControl, Share, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { BOOKING_STATUS_LABELS } from '@/api/endpoints';
import {
  useBookings,
  useCancelBooking,
  useMyReferrals,
  useMySeries,
  useStopSeries,
} from '@/api/hooks';
import { Button, Card, Divider, EmptyState, useColors } from '@/components/ui';
import { BookingRow, formatWhen } from '@/components/booking-row';

type Tab = 'upcoming' | 'past';

export default function CustomerBookings() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>('upcoming');
  const [refreshing, setRefreshing] = useState(false);

  const bookings = useBookings(tab === 'upcoming' ? { upcoming: true } : { past: true });
  const cancel = useCancelBooking();
  const seriesList = useMySeries();
  const stopSeries = useStopSeries();

  const running = (seriesList.data ?? []).filter((item) => item.status === 'active');
  const referrals = useMyReferrals();

  async function shareCode() {
    const code = referrals.data?.code;
    if (!code) return;
    await Share.share({
      message: `Book on BarberShop with my code ${code}. You and I both get a credit when your first appointment is done.`,
    });
  }

  const rows = bookings.data?.results ?? [];

  async function onRefresh() {
    setRefreshing(true);
    await bookings.refetch();
    setRefreshing(false);
  }

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <View
        className="flex-row gap-2 px-4 pb-3"
        style={{ paddingTop: insets.top + 8 }}>
        {(['upcoming', 'past'] as Tab[]).map((option) => {
          const selected = tab === option;
          return (
            <Text
              key={option}
              onPress={() => setTab(option)}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              className="rounded-full px-4 py-2 text-sm font-semibold capitalize"
              style={{
                color: selected ? colors.accentText : colors.textMuted,
                backgroundColor: selected ? colors.accent : colors.surface,
              }}>
              {option}
            </Text>
          );
        })}
      </View>

      <FlatList
        data={rows}
        keyExtractor={(item) => item.reference}
        contentContainerStyle={{ paddingBottom: insets.bottom + 24, gap: 12 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        ItemSeparatorComponent={() => <View style={{ height: 12 }} />}
        ListHeaderComponent={
          <View className="gap-3">
            {/* Only on the upcoming tab: a run whose next visit has been and
                gone is history, and listing it there would read as an
                appointment that is still coming. */}
            {referrals.data?.code ? (
              <View className="px-4">
                <Card className="gap-2">
                  <View className="flex-row items-center justify-between">
                    <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                      Give a friend a credit
                    </Text>
                    <Ionicons name="gift-outline" size={18} color={colors.accent} />
                  </View>
                  <Text className="text-xs" style={{ color: colors.textMuted }}>
                    They book with this code, and you both get points once their first
                    appointment is done - not when they book it, in case they do not.
                  </Text>
                  <Text
                    className="text-2xl font-bold tracking-widest"
                    style={{ color: colors.accent }}
                    testID="my-referral-code">
                    {referrals.data.code}
                  </Text>
                  {referrals.data.given_count > 0 ? (
                    <>
                      <Divider className="my-1" />
                      <Text className="text-xs" style={{ color: colors.textSubtle }}>
                        {referrals.data.given_count}{' '}
                        {referrals.data.given_count === 1 ? 'person has' : 'people have'}{' '}
                        used it · {referrals.data.rewarded_count} completed
                      </Text>
                    </>
                  ) : null}
                  <Button
                    variant="secondary"
                    onPress={() => void shareCode()}
                    testID="share-referral-code">
                    Share my code
                  </Button>
                </Card>
              </View>
            ) : null}

            {tab === 'upcoming' && running.length > 0 ? (
              <View className="px-4">
                <Text className="pb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                  Regular visits
                </Text>
                <View className="gap-2">
                  {running.map((item) => (
                    <Card key={item.id} className="gap-2">
                      <View className="flex-row items-center justify-between">
                        <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                          {item.service_names.join(', ') || 'Your regular visits'}
                        </Text>
                        <Ionicons name="repeat" size={18} color={colors.accent} />
                      </View>
                      <Text className="text-xs" style={{ color: colors.textMuted }}>
                        Every {item.interval_days} days, {item.total_occurrences}{' '}
                        visits
                        {item.next_starts_at
                          ? ` · next ${formatWhen(item.next_starts_at)}`
                          : ' · all booked'}
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textSubtle }}>
                        {item.created_occurrences} of {item.total_occurrences} booked. Each
                        one is paid for separately.
                      </Text>
                      <Button
                        variant="ghost"
                        onPress={() => void stopSeries.mutateAsync(item.id)}
                        loading={stopSeries.isPending && stopSeries.variables?.vars === item.id}
                        testID={`stop-series-${item.id}`}>
                        Stop these visits
                      </Button>
                      <Text className="text-2xs" style={{ color: colors.textSubtle }}>
                        Visits already booked stay on your calendar - each is paid for
                        on its own, so cancel any one of them on its own.
                      </Text>
                    </Card>
                  ))}
                </View>
              </View>
            ) : null}
            {rows.length ? (
              <Text className="px-4 pb-1 text-xs" style={{ color: colors.textSubtle }}>
                {rows.length} {rows.length === 1 ? 'booking' : 'bookings'}
              </Text>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <View className="px-4">
            <BookingRow
              booking={item}
              perspective="customer"
              statusLabel={BOOKING_STATUS_LABELS[item.status]}
              onPress={() => router.push(`/(customer)/booking/${item.reference}`)}
              onCancel={
                item.can_be_cancelled
                  ? () => cancel.mutate({ reference: item.reference })
                  : undefined
              }
              cancelling={cancel.isPending && cancel.variables?.reference === item.reference}
            />
          </View>
        )}
        ListEmptyComponent={
          bookings.isLoading ? null : bookings.isError ? (
            <EmptyState
              icon="cloud-offline-outline"
              title="Could not load your bookings"
              body={errorMessage(bookings.error)}
              action={<Button variant="secondary" onPress={() => void bookings.refetch()}>Try again</Button>}
            />
          ) : tab === 'upcoming' ? (
            <EmptyState
              icon="calendar-outline"
              title="Nothing booked"
              body="When you book a shop it will show up here, with the time and what it cost."
              action={<Button onPress={() => router.push('/(customer)/home')}>Find a shop</Button>}
            />
          ) : (
            <EmptyState icon="time-outline" title="No history yet" body="Past visits appear here." />
          )
        }
      />

      {/* A cancel that fails should say so, not vanish. */}
      {cancel.isError ? (
        <View className="px-4 pb-4">
          <Card>
            <Text className="text-sm" style={{ color: colors.danger }}>
              {errorMessage(cancel.error, 'Could not cancel that booking.')}
            </Text>
          </Card>
        </View>
      ) : null}
    </View>
  );
}