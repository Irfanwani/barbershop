import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { BOOKING_STATUS_LABELS } from '@/api/endpoints';
import { deadlineSummary, formatPaise, paymentSummary } from '@/lib/money';
import {
  useBooking,
  useCancelBooking,
  useCreateOrder,
  useCreateReview,
  useCreateTipOrder,
} from '@/api/hooks';
import { Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { formatRelative, formatWhen } from '@/components/booking-row';
import { RescheduleSheet } from '@/components/reschedule-sheet';

export default function BookingDetailScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { reference } = useLocalSearchParams<{ reference: string }>();

  const booking = useBooking(reference ?? null);
  const cancel = useCancelBooking();
  const [moving, setMoving] = useState(false);
  const order = useCreateOrder();

  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [showReview, setShowReview] = useState(false);
  const [showTip, setShowTip] = useState(false);

  if (booking.isLoading) {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: colors.background }}>
        <Text style={{ color: colors.textMuted }}>Loading…</Text>
      </View>
    );
  }

  if (booking.isError || !booking.data) {
    return (
      <View className="flex-1" style={{ backgroundColor: colors.background }}>
        <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="m-3" />
        <EmptyState icon="alert-circle-outline" title="Could not load this booking" body={errorMessage(booking.error)} />
      </View>
    );
  }

  const record = booking.data;

  async function startPayment() {
    setPayError(null);
    setPaying(true);
    try {
      const result = await order.mutateAsync(record.reference);
      await openCheckout(result);
    } catch (caught) {
      setPayError(errorMessage(caught, 'Could not start the payment.'));
    } finally {
      setPaying(false);
    }
  }

  /**
   * The Razorpay sheet needs the native SDK. It is not bundled here: a payment
   * screen that cannot take a card is worse than one that says payments need a
   * build with `expo-dev-client`, so the integration point is isolated in one
   * function rather than spread across the checkout flow.
   */
  async function openCheckout(result: { razorpay: { key_id: string; order_id: string } }) {
    try {
      // Imported lazily: react-native-razorpay has a native module, and a static
      // import would fail the JS bundle for every screen in the app.
      const { default: RazorpayCheckout } = await import('react-native-razorpay');
      await RazorpayCheckout.open({
        key: result.razorpay.key_id,
        order_id: result.razorpay.order_id,
      });
      await booking.refetch();
    } catch {
      setPayError(
        'The payment sheet is not available in this build. Pay at the shop instead.',
      );
    }
  }

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
        <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            {record.provider.display_name}
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {formatWhen(record.starts_at)} · {formatRelative(record.starts_at)}
          </Text>
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            Reference {record.reference}
          </Text>
        </View>

        <Card className="gap-2">
          {record.items.map((item, index) => (
            <View key={item.id}>
              {index > 0 ? <Divider className="my-2" /> : null}
              <View className="flex-row justify-between">
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {item.name}
                </Text>
                <Text className="text-sm" style={{ color: colors.text }}>
                  {item.unit_price_display}
                </Text>
              </View>
            </View>
          ))}
          <Divider className="my-2" />
          <View className="flex-row justify-between">
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              Service fee
            </Text>
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              {record.platform_fee_display}
            </Text>
          </View>
          {record.deposit > 0 ? (
            <>
              <View className="flex-row justify-between">
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  Deposit to secure the slot
                </Text>
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {record.deposit_display}
                </Text>
              </View>
              <View className="flex-row justify-between">
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  Due at the shop
                </Text>
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {record.balance_display}
                </Text>
              </View>
            </>
          ) : null}

          {record.amount_paid > 0 ? (
            <View className="flex-row justify-between">
              <Text className="text-sm font-medium" style={{ color: colors.success }}>
                Paid so far
              </Text>
              <Text className="text-sm font-medium" style={{ color: colors.success }}>
                {formatPaise(record.amount_paid)}
              </Text>
            </View>
          ) : null}

          <Divider className="my-2" />
          <View className="flex-row justify-between">
            <Text className="text-base font-semibold" style={{ color: colors.text }}>
              Total
            </Text>
            <Text className="text-base font-semibold" style={{ color: colors.text }}>
              {record.total_display}
            </Text>
          </View>
        </Card>

        <Card className="gap-1">
          <Text className="text-sm font-medium" style={{ color: colors.text }}>
            {BOOKING_STATUS_LABELS[record.status]}
          </Text>
          <Text className="text-xs" style={{ color: colors.textMuted }}>
            {paymentSummary(record)} · booked {formatWhen(record.created_at)}
          </Text>
          {record.cancellation_reason ? (
            <Text className="text-xs" style={{ color: colors.textMuted }}>
              {record.cancellation_reason}
            </Text>
          ) : null}
        </Card>

        {payError ? <FormError message={payError} /> : null}

        {record.requires_deposit && !record.is_paid ? (
          <Button onPress={startPayment} loading={paying} testID="booking-pay">
            Pay deposit {record.deposit_display}
          </Button>
        ) : null}

        {record.deposit > 0 &&
        record.amount_paid >= record.deposit &&
        !record.is_paid &&
        record.status === 'confirmed' ? (
          <Button onPress={startPayment} loading={paying} testID="booking-pay-balance">
            Pay remaining {formatPaise(record.amount_due)} now
          </Button>
        ) : null}

        {record.deposit > 0 && record.can_be_cancelled ? (
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            {deadlineSummary(record)}
          </Text>
        ) : null}

        {record.can_be_cancelled ? (
          <View className="flex-row gap-2">
            <Button
              className="flex-1"
              variant="ghost"
              onPress={() => setMoving(true)}
              testID="booking-reschedule">
              Change the time
            </Button>
            <Button
              className="flex-1"
              variant="ghost"
              onPress={() => cancel.mutate({ reference: record.reference })}
              loading={cancel.isPending}
              testID="booking-cancel">
              Cancel booking
            </Button>
          </View>
        ) : null}

        <RescheduleSheet
          reference={record.reference}
          providerId={record.provider.id}
          visible={moving}
          onClose={() => setMoving(false)}
        />

        {record.status === 'completed' ? (
          <View className="gap-2">
            <Button
              variant="secondary"
              icon="star-outline"
              onPress={() => setShowReview(true)}
              testID="booking-review">
              Leave a review
            </Button>
            <Button
              variant="ghost"
              icon="gift-outline"
              onPress={() => setShowTip(true)}
              testID="booking-tip">
              Add a tip
            </Button>
          </View>
        ) : null}

        {record.notes ? (
          <Card>
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              {record.notes}
            </Text>
          </Card>
        ) : null}
      </ScrollView>

      {showTip ? (
        <TipSheet
          reference={record.reference}
          staffId={record.staff?.id ?? null}
          onClose={() => setShowTip(false)}
          onDone={() => setShowTip(false)}
        />
      ) : null}

      {showReview ? (
        <ReviewSheet
          bookingId={record.id}
          providerId={record.provider.id}
          providerName={record.provider.display_name}
          onClose={() => setShowReview(false)}
          onDone={() => {
            setShowReview(false);
            void booking.refetch();
          }}
        />
      ) : null}
    </View>
  );
}

function ReviewSheet({
  bookingId,
  providerId,
  providerName,
  onClose,
  onDone,
}: {
  bookingId: number;
  providerId: number;
  providerName: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const create = useCreateReview();

  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    try {
      await create.mutateAsync({ provider: providerId, booking: bookingId, rating, comment });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, 'Could not save that review.'));
    }
  }

  return (
    <View className="absolute inset-0 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      <View
        className="gap-4 rounded-t-3xl p-5"
        style={{ backgroundColor: colors.background, paddingBottom: insets.bottom + 24 }}>
        <View className="flex-row items-center justify-between">
          <Text className="text-lg font-semibold" style={{ color: colors.text }}>
            How was {providerName}?
          </Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
            <Ionicons name="close" size={22} color={colors.textMuted} />
          </Pressable>
        </View>

        <View className="flex-row gap-2">
          {[1, 2, 3, 4, 5].map((value) => (
            <Pressable
              key={value}
              onPress={() => setRating(value)}
              accessibilityRole="radio"
              accessibilityState={{ selected: rating === value }}
              accessibilityLabel={`${value} star${value === 1 ? '' : 's'}`}
              testID={`review-star-${value}`}>
              <Ionicons
                name={value <= rating ? 'star' : 'star-outline'}
                size={32}
                color={value <= rating ? '#F59E0B' : colors.textSubtle}
              />
            </Pressable>
          ))}
        </View>

        <Field
          placeholder="Anything worth saying?"
          value={comment}
          onChangeText={setComment}
          multiline
          numberOfLines={4}
          testID="review-comment"
        />

        <FormError message={error} />

        <Button onPress={submit} loading={create.isPending} testID="review-submit">
          Post review
        </Button>
      </View>
    </View>
  );
}

/**
 * A tip on a finished appointment.
 *
 * Presented beside "leave a review" because that is the moment somebody is
 * thinking about the person who just cut their hair, and a tip asked for
 * somewhere else is a tip that never arrives.
 */
function TipSheet({
  reference,
  staffId,
  onClose,
  onDone,
}: {
  reference: string;
  staffId: number | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const tip = useCreateTipOrder();
  const booking = useBooking(reference);

  const [amount, setAmount] = useState(5000);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);
    try {
      const result = await tip.mutateAsync({
        reference,
        amount,
        ...(staffId === null ? {} : { staff: staffId }),
      });
      const razorpay = (result as { razorpay?: { key_id: string; order_id: string } })?.razorpay;
      if (!razorpay) throw new Error('missing checkout details');
      const { default: RazorpayCheckout } = await import('react-native-razorpay');
      await RazorpayCheckout.open({ key: razorpay.key_id, order_id: razorpay.order_id });
      await booking.refetch();
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, 'Could not send that tip.'));
    }
  }

  return (
    <View className="absolute inset-0 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      <View
        className="gap-4 rounded-t-3xl p-5"
        style={{ backgroundColor: colors.background, paddingBottom: insets.bottom + 24 }}>
        <View className="flex-row items-center justify-between">
          <Text className="text-lg font-semibold" style={{ color: colors.text }}>
            Add a tip
          </Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
            <Ionicons name="close" size={22} color={colors.textMuted} />
          </Pressable>
        </View>

        <Text className="text-sm" style={{ color: colors.textMuted }}>
          The whole amount goes to {booking.data?.staff?.name ?? 'the shop'} - the platform takes no
          cut of a tip.
        </Text>

        <View className="flex-row flex-wrap gap-2">
          {[2000, 5000, 10000, 20000].map((value) => (
            <Pressable
              key={value}
              onPress={() => setAmount(value)}
              accessibilityRole="radio"
              accessibilityState={{ selected: amount === value }}
              testID={`tip-amount-${value}`}>
              <View
                className="rounded-full px-4 py-2"
                style={{
                  backgroundColor: amount === value ? colors.accent : colors.surface,
                }}>
                <Text
                  className="text-sm font-medium"
                  style={{ color: amount === value ? colors.accentText : colors.text }}>
                  {formatPaise(value)}
                </Text>
              </View>
            </Pressable>
          ))}
        </View>

        <FormError message={error} />

        <Button onPress={submit} loading={tip.isPending} testID="tip-submit">
          Send {formatPaise(amount)}
        </Button>
      </View>
    </View>
  );
}
