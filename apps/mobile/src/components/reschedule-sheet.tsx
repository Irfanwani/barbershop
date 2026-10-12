import { useState } from 'react';
import { Modal, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { errorMessage } from '@/api/client';
import { useAvailability, useRescheduleBooking } from '@/api/hooks';
import { Button, Card, Divider, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import { formatPaise } from '@/lib/money';
import type { RescheduleRefused } from '@/types/api';

/**
 * Move an appointment to a different time.
 *
 * Three outcomes, and all three are shown rather than swallowed:
 *
 * - it moved
 * - it did not, because the price changed since the customer agreed, in which
 *   case both totals are shown and agreeing is a separate, explicit tap
 * - it did not, because it fell inside the cancellation window and became a
 *   cancellation instead, which is the honest answer and not a failure to
 *   hide behind a generic error
 */
export function RescheduleSheet({
  reference,
  providerId,
  visible,
  onClose,
}: {
  reference: string;
  providerId: number;
  visible: boolean;
  onClose: () => void;
}) {
  const colors = useColors();
  const availability = useAvailability(providerId);
  const reschedule = useRescheduleBooking();

  const [error, setError] = useState<string | null>(null);
  const [priceChange, setPriceChange] = useState<RescheduleRefused | null>(null);
  const [cancelled, setCancelled] = useState<RescheduleRefused | null>(null);

  const slots = (availability.data?.slots ?? []).filter((slot) => slot.is_available);

  async function move(starts_at: string, acceptPriceChange = false) {
    setError(null);
    try {
      const result = await reschedule.mutateAsync({ reference, starts_at, acceptPriceChange });

      if ('reference' in result) {
        onClose();
        return;
      }

      if (result.cancelled) {
        setCancelled(result);
        return;
      }
      setPriceChange(result);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not move that appointment.'));
    }
  }

  function reset() {
    setPriceChange(null);
    setCancelled(null);
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View className="flex-1 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
        <View
          className="max-h-[80%] rounded-t-3xl"
          style={{ backgroundColor: colors.surface, padding: 20, paddingBottom: 32, gap: 16 }}>
          <View className="flex-row items-center justify-between">
            <Text className="text-lg font-bold" style={{ color: colors.text }}>
              {cancelled ? 'Cancelled instead' : priceChange ? 'The price changed' : 'Change the time'}
            </Text>
            <Button variant="ghost" onPress={onClose} testID="reschedule-close">
              Close
            </Button>
          </View>

          <FormError message={error} />

          {cancelled ? (
            <View className="gap-3">
              <View className="flex-row items-start gap-2">
                <Ionicons name="information-circle-outline" size={18} color={colors.warning} />
                <Text className="flex-1 text-sm leading-5" style={{ color: colors.textMuted }}>
                  {cancelled.message}
                </Text>
              </View>
              {cancelled.late_cancel_fee ? (
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  A cancellation fee of {formatPaise(cancelled.late_cancel_fee)} was charged, the
                  same as cancelling would have been.
                </Text>
              ) : null}
              <Button onPress={reset} testID="reschedule-ok">
                Got it
              </Button>
            </View>
          ) : priceChange ? (
            <View className="gap-3">
              <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
                {priceChange.message}
              </Text>
              <Card className="gap-2">
                <View className="flex-row justify-between">
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    You agreed to
                  </Text>
                  <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                    {formatPaise(priceChange.old_total ?? 0)}
                  </Text>
                </View>
                <Divider />
                <View className="flex-row justify-between">
                  <Text className="text-sm" style={{ color: colors.text }}>
                    Now
                  </Text>
                  <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                    {formatPaise(priceChange.new_total ?? 0)}
                  </Text>
                </View>
              </Card>
              <View className="flex-row gap-2">
                <Button className="flex-1" variant="ghost" onPress={reset} testID="price-decline">
                  Leave it
                </Button>
                <Button
                  className="flex-1"
                  onPress={() => {
                    const target = slots[0]?.starts_at;
                    if (target) void move(target, true);
                  }}
                  testID="price-accept">
                  Accept and move
                </Button>
              </View>
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ gap: 12 }}>
              {availability.isLoading ? (
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  Loading times…
                </Text>
              ) : slots.length === 0 ? (
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  Nothing free in the next fortnight. Try again closer to the day, or join
                  the waitlist on the shop's page.
                </Text>
              ) : (
                slots.slice(0, 40).map((slot) => (
                  <Button
                    key={slot.starts_at}
                    variant="secondary"
                    onPress={() => void move(slot.starts_at)}
                    testID={`move-to-${slot.starts_at}`}>
                    {formatWhen(slot.starts_at)}
                  </Button>
                ))
              )}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

function formatWhen(iso: string): string {
  const when = new Date(iso);
  const today = new Date();
  const day = when.toDateString() === today.toDateString() ? 'Today' : when.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
  return `${day}, ${when.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true })}`;
}
