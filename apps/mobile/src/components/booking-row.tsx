import { Text, View } from 'react-native';

import { useColors , Card } from '@/components/ui';
import type { Booking } from '@/types/api';

type Tone = 'positive' | 'neutral' | 'danger';

/**
 * One booking, in a list.
 *
 * Shows the reference prominently. It is the only identifier a customer can read
 * out over the phone, and the old app generated sequential numbers, which made it
 * a way to enumerate other people's appointments. The current ones look like
 * `BK-7QK4M2`.
 */
export function BookingRow({
  booking,
  perspective,
  statusLabel,
  onPress,
  onCancel,
  cancelling = false,
  actions,
}: {
  booking: Booking;
  perspective: 'customer' | 'provider';
  statusLabel: string;
  onPress?: () => void;
  onCancel?: () => void;
  cancelling?: boolean;
  actions?: React.ReactNode;
}) {
  const colors = useColors();
  const tone = toneFor(booking.status);

  return (
    <Card onPress={onPress} className="gap-3">
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 gap-0.5">
          <Text className="text-base font-semibold" style={{ color: colors.text }}>
            {perspective === 'customer' ? booking.provider.display_name : booking.customer.display_name}
          </Text>
          <Text className="text-xs" style={{ color: colors.textMuted }}>
            {formatWhen(booking.starts_at)}
          </Text>
        </View>
        <View
          className="rounded-full px-2.5 py-1"
          style={{
            backgroundColor:
              tone === 'positive'
                ? `${colors.success}18`
                : tone === 'danger'
                  ? `${colors.danger}18`
                  : colors.surfaceRaised,
          }}>
          <Text
            className="text-2xs font-semibold"
            style={{
              color: tone === 'positive' ? colors.success : tone === 'danger' ? colors.danger : colors.textMuted,
            }}>
            {statusLabel}
          </Text>
        </View>
      </View>

      <View className="flex-row items-center justify-between">
        <Text className="text-xs" style={{ color: colors.textSubtle }}>
          {booking.reference} · {booking.items.length}{' '}
          {booking.items.length === 1 ? 'service' : 'services'}
        </Text>
        <Text className="text-sm font-semibold" style={{ color: colors.text }}>
          {booking.total_display}
        </Text>
      </View>

      {actions ? <View className="flex-row gap-2">{actions}</View> : null}

      {onCancel ? (
        <Text
          onPress={onCancel}
          accessibilityRole="button"
          accessibilityState={{ disabled: cancelling }}
          className="self-start text-xs font-semibold"
          style={{ color: cancelling ? colors.textSubtle : colors.danger }}>
          {cancelling ? 'Cancelling…' : 'Cancel booking'}
        </Text>
      ) : null}
    </Card>
  );
}

function toneFor(status: Booking['status']): Tone {
  switch (status) {
    case 'confirmed':
    case 'completed':
      return 'positive';
    case 'cancelled_by_customer':
    case 'cancelled_by_provider':
    case 'refunded':
      return 'danger';
    default:
      return 'neutral';
  }
}

/** "Tue 14 Oct, 3:30 PM" in the device's own time zone. */
export function formatWhen(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** "in 2 hours", "in 3 days", "3 days ago". */
export function formatRelative(iso: string): string {
  const target = new Date(iso).getTime();
  const now = Date.now();
  const minutes = Math.round((target - now) / 60_000);
  const abs = Math.abs(minutes);

  if (abs < 60) return minutes >= 0 ? `in ${abs} min` : `${abs} min ago`;
  const hours = Math.round(abs / 60);
  if (hours < 24) return minutes >= 0 ? `in ${hours} h` : `${hours} h ago`;
  const days = Math.round(hours / 24);
  return minutes >= 0 ? `in ${days} d` : `${days} d ago`;
}