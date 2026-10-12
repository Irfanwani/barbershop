import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import {
  useLeaveWaitlist,
  useRespondToOffer,
  useWaitlist,
  useWaitlistOffers,
} from '@/api/hooks';
import { Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { FormError } from '@/components/field';

/**
 * The waitlist, and anything being held for you right now.
 *
 * An offer is a countdown with a slot behind it, so it sits at the top of the
 * screen where it cannot be missed, and it shows what happens if the countdown
 * runs out — "yours until 3:15pm" is not the same as "yours", and a customer
 * who is not told that will be woken by somebody else taking their slot.
 */
export default function WaitlistScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const offers = useWaitlistOffers();
  const entries = useWaitlist();
  const leave = useLeaveWaitlist();
  const respond = useRespondToOffer();

  const [error, setError] = useState<string | null>(null);
  const [takingId, setTakingId] = useState<number | null>(null);

  const live = offers.data ?? [];
  const waiting = (entries.data ?? []).filter((entry) => entry.status === 'waiting');

  async function take(id: number) {
    setError(null);
    setTakingId(id);
    try {
      const booking = await respond.mutateAsync({ id, action: 'accept' });
      router.replace(`/(customer)/booking/${booking.reference}`);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not take that slot.'));
    } finally {
      setTakingId(null);
    }
  }

  async function pass(id: number) {
    setError(null);
    try {
      await respond.mutateAsync({ id, action: 'decline' });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not let that slot go.'));
    }
  }

  async function quit(id: number) {
    setError(null);
    try {
      await leave.mutateAsync(id);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not leave the waitlist.'));
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 20 }}
      keyboardShouldPersistTaps="handled">
      <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

      <View className="gap-1">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Waitlist
        </Text>
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          When a booked slot is cancelled we offer it to whoever joined first.
        </Text>
      </View>

      <FormError message={error} />

      {live.length > 0 ? (
        <View className="gap-3">
          {live.map((offer) => (
            <Card key={offer.id} className="gap-3">
              <View className="gap-1">
                <View className="flex-row items-center gap-2">
                  <Ionicons name="flash" size={16} color={colors.accent} />
                  <Text className="text-base font-semibold" style={{ color: colors.text }}>
                    {offer.shop_name}
                  </Text>
                </View>
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {offer.service_name}
                  {offer.staff_name ? ` with ${offer.staff_name}` : ''}
                </Text>
              </View>

              <View
                className="rounded-xl px-3 py-2"
                style={{ backgroundColor: colors.surfaceRaised }}>
                <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                  {formatWhen(offer.starts_at)}
                </Text>
                {offer.can_accept ? (
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    Held for you until {formatClock(offer.expires_at)}, then it goes to
                    someone else.
                  </Text>
                ) : (
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    This hold has run out. It may already have gone to someone else.
                  </Text>
                )}
              </View>

              <View className="flex-row gap-2">
                <Button
                  className="flex-1"
                  variant="ghost"
                  onPress={() => void pass(offer.id)}
                  testID={`decline-offer-${offer.id}`}>
                  Not for me
                </Button>
                <Button
                  className="flex-1"
                  onPress={() => void take(offer.id)}
                  loading={takingId === offer.id}
                  disabled={!offer.can_accept}
                  testID={`accept-offer-${offer.id}`}>
                  Take it
                </Button>
              </View>
            </Card>
          ))}
        </View>
      ) : null}

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Waiting for
        </Text>

        {waiting.length === 0 ? (
          <EmptyState
            icon="notifications-outline"
            title="Nothing on the waitlist"
            body="Open a shop, pick a time that is already taken, and join the waitlist for that slot."
          />
        ) : (
          <Card>
            {waiting.map((entry, index) => (
              <View key={entry.id}>
                {index > 0 ? <Divider className="my-3" /> : null}
                <View className="gap-1">
                  <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                    {entry.provider_name}
                  </Text>
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    {entry.service_name}
                    {entry.staff_name ? ` · ${entry.staff_name}` : ''} · any time between{' '}
                    {formatShort(entry.window_start)} and {formatShort(entry.window_end)}
                  </Text>
                </View>
                <Button
                  variant="ghost"
                  className="mt-2 self-start"
                  onPress={() => void quit(entry.id)}
                  testID={`leave-waitlist-${entry.id}`}>
                  Leave
                </Button>
              </View>
            ))}
          </Card>
        )}
      </View>
    </ScrollView>
  );
}

export function formatClock(iso: string): string {
  const when = new Date(iso);
  return when
    .toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true })
    .toLowerCase()
    .replace(' ', '');
}

export function formatWhen(iso: string): string {
  const when = new Date(iso);
  const today = new Date();
  const sameDay = when.toDateString() === today.toDateString();
  const clock = formatClock(iso);
  return sameDay ? `Today at ${clock}` : `${when.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' })} at ${clock}`;
}

function formatShort(iso: string): string {
  const when = new Date(iso);
  return `${when.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} ${formatClock(iso)}`;
}