import { useState } from 'react';
import { FlatList, RefreshControl, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { BOOKING_STATUS_LABELS } from '@/api/endpoints';
import { useBookings, useCancelBooking } from '@/api/hooks';
import { Button, Card, EmptyState, useColors } from '@/components/ui';
import { BookingRow } from '@/components/booking-row';

type Tab = 'upcoming' | 'past';

export default function CustomerBookings() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>('upcoming');
  const [refreshing, setRefreshing] = useState(false);

  const bookings = useBookings(tab === 'upcoming' ? { upcoming: true } : { past: true });
  const cancel = useCancelBooking();

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
          rows.length ? (
            <Text className="px-4 pb-1 text-xs" style={{ color: colors.textSubtle }}>
              {rows.length} {rows.length === 1 ? 'booking' : 'bookings'}
            </Text>
          ) : null
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