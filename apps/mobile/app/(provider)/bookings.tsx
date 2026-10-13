import { useState } from 'react';
import { FlatList, RefreshControl, Text, View } from 'react-native';

import { errorMessage } from '@/api/client';
import type { Booking } from '@/types/api';
import { BOOKING_STATUS_LABELS } from '@/api/endpoints';
import { useBookings, useCollectBooking, useTransitionBooking } from '@/api/hooks';
import { Button, Card, EmptyState, useColors } from '@/components/ui';
import { BookingRow } from '@/components/booking-row';
import { CustomerRiskSheet } from '@/components/customer-risk-sheet';
import { formatPaise } from '@/lib/money';

type Tab = 'today' | 'upcoming' | 'past';

export default function ProviderBookings() {
  const colors = useColors();
  const [tab, setTab] = useState<Tab>('today');
  const [refreshing, setRefreshing] = useState(false);

  const params =
    tab === 'past' ? { past: true } : tab === 'today' ? { upcoming: true } : { upcoming: true };

  const bookings = useBookings(params);
  const transition = useTransitionBooking();
  const collect = useCollectBooking();
  const [collectError, setCollectError] = useState<string | null>(null);

  const rows = bookings.data?.results ?? [];
  const [riskFor, setRiskFor] = useState<{ id: number; name: string } | null>(null);

  async function onRefresh() {
    setRefreshing(true);
    await bookings.refetch();
    setRefreshing(false);
  }

  async function takeBalance(reference: string, amount: number) {
    setCollectError(null);
    try {
      await collect.mutateAsync({ reference, amount, method: 'cash' });
    } catch (caught) {
      setCollectError(errorMessage(caught, 'Could not record that payment.'));
    }
  }

  function pendingActions(booking: Booking) {
    const { reference, status } = booking;

    // What is still owed on an appointment that is under way. Recording this
    // is separate from marking the appointment done: a customer who paid and
    // then walked out has still been paid.
    const balanceDue =
      booking.amount_due > 0 && ['confirmed', 'completed'].includes(status)
        ? booking.amount_due
        : 0;
    if (status === 'awaiting_confirmation') {
      return (
        <>
          <Button
            className="flex-1"
            onPress={() => transition.mutate({ reference, action: 'accept' })}
            loading={transition.isPending && transition.variables?.reference === reference}
            testID={`accept-${reference}`}>
            Accept
          </Button>
          <Button
            variant="ghost"
            className="flex-1"
            onPress={() => transition.mutate({ reference, action: 'decline' })}
            testID={`decline-${reference}`}>
            Decline
          </Button>
        </>
      );
    }

    if (status === 'confirmed') {
      return (
        <>
          {balanceDue > 0 ? (
            <Button
              variant="secondary"
              className="flex-1"
              onPress={() => takeBalance(reference, balanceDue)}
              loading={collect.isPending && collect.variables?.reference === reference}
              testID={`collect-${reference}`}>
              Take {formatPaise(balanceDue)}
            </Button>
          ) : null}
          <Button
            variant="secondary"
            className="flex-1"
            onPress={() => transition.mutate({ reference, action: 'complete' })}
            testID={`complete-${reference}`}>
            Mark done
          </Button>
          <Button
            variant="ghost"
            className="flex-1"
            onPress={() => transition.mutate({ reference, action: 'no-show' })}
            testID={`noshow-${reference}`}>
            No show
          </Button>
        </>
      );
    }

    return null;
  }

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <View className="flex-row gap-2 px-4 py-3">
        {(['today', 'upcoming', 'past'] as Tab[]).map((option) => {
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
        contentContainerStyle={{ paddingBottom: 24, gap: 12 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        renderItem={({ item }) => (
          <View className="px-4">
            <BookingRow
              booking={item}
              perspective="provider"
              statusLabel={BOOKING_STATUS_LABELS[item.status]}
              actions={pendingActions(item)}
              onPress={() =>
                setRiskFor({ id: item.customer.id, name: item.customer.display_name })
              }
            />
          </View>
        )}
        ListEmptyComponent={
          bookings.isLoading ? null : (
            <EmptyState
              icon="calendar-outline"
              title={
                tab === 'past' ? 'No completed bookings yet' : 'Nothing booked'
              }
              body={
                tab === 'past'
                  ? 'Finished appointments show up here, and they count towards your rating.'
                  : 'Customers see your menu and hours when they search. Check both are right.'
              }
            />
          )
        }
      />

      {collectError ? (
        <View className="px-4 pb-2">
          <Text className="text-sm font-medium" style={{ color: colors.danger }}>
            {collectError}
          </Text>
        </View>
      ) : null}

      {transition.isError ? (
        <View className="px-4 pb-4">
          <Card>
            <Text className="text-sm" style={{ color: colors.danger }}>
              {errorMessage(transition.error, 'Could not update that booking.')}
            </Text>
          </Card>
        </View>
      ) : null}
      {riskFor ? (
        <CustomerRiskSheet
          customerId={riskFor.id}
          displayName={riskFor.name}
          onClose={() => setRiskFor(null)}
        />
      ) : null}
    </View>
  );
}