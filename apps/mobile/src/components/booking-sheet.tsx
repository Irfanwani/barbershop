import { useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import {
  useConsultationPrompt,
  useCreateBooking,
  useCreateSeries,
  useJoinWaitlist,
  usePointsBalance,
  useQuote,
  useShopStaff,
} from '@/api/hooks';
import { Button, Divider, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { formatWhen } from '@/components/booking-row';
import { cancellationNote, formatPaise } from '@/lib/money';
import type {
  Availability,
  ConsultationQuestion,
  ProviderDetail,
  Service,
} from '@/types/api';

/** How often somebody actually wants to be in a chair. */
const INTERVALS = [
  { days: 14, label: 'Every 2 weeks' },
  { days: 28, label: 'Every 4 weeks' },
  { days: 42, label: 'Every 6 weeks' },
  { days: 56, label: 'Every 8 weeks' },
] as const;

const VISIT_COUNTS = [3, 4, 6, 8] as const;

/**
 * Choosing services, a time and confirming the price.
 *
 * The price shown is the server's, fetched at the moment the customer picks a
 * time — not a total computed on the phone. The old app did the arithmetic
 * client-side and posted it straight to the API, which meant any client could
 * post whatever it liked. Here the app asks, and the booking request carries no
 * price at all.
 */
export function BookingSheet({
  visible,
  onClose,
  provider,
  availability,
}: {
  visible: boolean;
  onClose: () => void;
  provider: ProviderDetail;
  availability?: Availability;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [selected, setSelected] = useState<Service[]>([]);
  const [slot, setSlot] = useState<string | null>(null);
  // null means "whoever is free". A shop that has named nobody has no list, so
  // this stays null and behaves exactly as it did before staff existed.
  const [staffId, setStaffId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Empty string rather than null: an untouched field and a cleared one are
  // the same thing here, and "" is what the server reads as "no code".
  const [promoCode, setPromoCode] = useState('');
  const [redeemPoints, setRedeemPoints] = useState(false);
  // Answers keyed by question id. Empty string means "not answered", which is
  // different from a question that is not on the form at all - only the second
  // one may be left out.
  const [answers, setAnswers] = useState<Record<number, string>>({});
  // Off by default. Most bookings are one appointment, and a sheet that opens
  // offering six is a sheet that has to be read before it can be used.
  // Optional and last in the sheet: most bookings are not referred, and a
  // required-looking box for a promotion is a box people fill in with anything.
  const [referralCode, setReferralCode] = useState('');
  const [repeat, setRepeat] = useState(false);
  const [intervalDays, setIntervalDays] = useState(28);
  const [visitCount, setVisitCount] = useState(6);

  const quote = useQuote();
  const series = useCreateSeries();
  const points = usePointsBalance(Boolean(slot));
  const prompt = useConsultationPrompt(
    provider.id,
    useMemo(() => selected.map((service) => service.id), [selected]),
  );
  const create = useCreateBooking();
  const joinWaitlist = useJoinWaitlist();
  const staff = useShopStaff(provider.id);
  const [onWaitlist, setOnWaitlist] = useState(false);

  // Someone who does not work the day being booked cannot be chosen. Offering
  // them and refusing at the server would be a worse version of the same thing.
  const bookable = (staff.data ?? []).filter((member) => member.is_open_today);

  const services = useMemo(
    () => provider.services.filter((service) => service.is_active),
    [provider.services],
  );

  const freeSlots = useMemo(
    () => (availability?.slots ?? []).filter((entry) => entry.is_available),
    [availability],
  );

  function toggle(service: Service) {
    setError(null);
    setSelected((current) =>
      current.some((item) => item.id === service.id)
        ? current.filter((item) => item.id !== service.id)
        : [...current, service],
    );
    // The quote depends on the choice, so any previous one is now wrong.
    quote.reset();
    // And so do the questions: a form attached to the service just added may
    // ask things the previous selection did not, and an answer given to a
    // question that is no longer on the form would be rejected at checkout.
    setAnswers({});
  }

  async function chooseTime(startsAt: string) {
    setError(null);
    setSlot(startsAt);
    await reprice(startsAt);
  }

  /**
   * Ask the server what it costs.
   *
   * Every one of these is sent to be *resolved*, not applied: the server looks
   * the code up, decides what the points are worth, and returns a total. The app
   * never does the arithmetic, which is what stops a modified client posting a
   * discount of its own.
   */
  async function reprice(at: string) {
    try {
      await quote.mutateAsync({
        provider: provider.id,
        services: selected.map((service) => service.id),
        starts_at: at,
        ...(promoCode.trim() ? { promo_code: promoCode.trim() } : {}),
        ...(redeemPoints && points.data ? { redeem_points: points.data.available } : {}),
      });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not price that slot.'));
    }
  }

  async function applyPromo() {
    if (!slot) return;
    setError(null);
    await reprice(slot);
  }

  async function togglePoints() {
    if (!slot) return;
    const next = !redeemPoints;
    setError(null);
    setRedeemPoints(next);
    try {
      await quote.mutateAsync({
        provider: provider.id,
        services: selected.map((service) => service.id),
        starts_at: slot,
        ...(promoCode.trim() ? { promo_code: promoCode.trim() } : {}),
        ...(next && points.data ? { redeem_points: points.data.available } : {}),
      });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not price that slot.'));
    }
  }

  async function addToWaitlist() {
    if (selected.length === 0) return;
    setError(null);
    try {
      // A window, not a slot: the whole point is to be told about the next
      // cancellation, not this one particular minute.
      const from = new Date();
      const until = new Date(from.getTime() + 14 * 24 * 60 * 60 * 1000);
      await joinWaitlist.mutateAsync({
        provider: provider.id,
        service: selected[0]!.id,
        ...(staffId ? { staff: staffId } : {}),
        window_start: from.toISOString(),
        window_end: until.toISOString(),
      });
      setOnWaitlist(true);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not join the waitlist.'));
    }
  }

  async function confirm() {
    if (!slot) return;
    setError(null);
    try {
      if (repeat) {
        // The server works out every later date from this first one. The app
        // never adds an interval, so a visit that gets skipped cannot drag the
        // rest of the run earlier.
        await series.mutateAsync({
          provider: provider.id,
          services: selected.map((service) => service.id),
          starts_at: slot,
          interval_days: intervalDays,
          total_occurrences: visitCount,
          ...(staffId ? { staff: staffId } : {}),
        });
        onClose();
        router.replace('/(customer)/bookings');
        return;
      }
      const asked = (prompt.data?.questions ?? []).filter((question) => {
        const value = (answers[question.id] ?? '').trim();
        return value.length > 0;
      });
      const booking = await create.mutateAsync({
        provider: provider.id,
        services: selected.map((service) => service.id),
        starts_at: slot,
        ...(referralCode.trim() ? { referral_code: referralCode.trim().toUpperCase() } : {}),
        ...(staffId ? { staff: staffId } : {}),
        ...(promoCode.trim() ? { promo_code: promoCode.trim() } : {}),
        ...(redeemPoints && points.data ? { redeem_points: points.data.available } : {}),
        answers: asked.map((question) => ({
          question: question.id,
          value: (answers[question.id] ?? '').trim(),
        })),
      });
      onClose();
      router.replace(`/(customer)/booking/${booking.reference}`);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not book that slot.'));
    }
  }

  const priced = quote.data;
  const questions = prompt.data?.questions ?? [];
  const missingRequired = questions.filter(
    (question) => question.is_required && !(answers[question.id] ?? '').trim(),
  ).length;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View className="flex-1 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
        <View
          className="max-h-[88%] rounded-t-3xl"
          style={{ backgroundColor: colors.background, paddingBottom: insets.bottom }}>
          <View className="items-center pt-3">
            <View className="h-1 w-10 rounded-full" style={{ backgroundColor: colors.border }} />
          </View>

          <View
            className="flex-row items-center justify-between px-5 py-4"
            style={{ borderBottomColor: colors.border, borderBottomWidth: 1 }}>
            <Text className="text-lg font-semibold" style={{ color: colors.text }}>
              Book at {provider.display_name}
            </Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
              <Ionicons name="close" size={22} color={colors.textMuted} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={{ padding: 20, gap: 20 }}>
            <View className="gap-2">
              <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                1 · What would you like?
              </Text>
              {services.map((service) => {
                const checked = selected.some((item) => item.id === service.id);
                return (
                  <Pressable
                    key={service.id}
                    onPress={() => toggle(service)}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked }}
                    testID={`book-service-${service.id}`}
                    className="flex-row items-center gap-3 rounded-2xl border px-4 py-3"
                    style={{
                      backgroundColor: checked ? `${colors.accent}12` : colors.surface,
                      borderColor: checked ? colors.accent : colors.border,
                    }}>
                    <Ionicons
                      name={checked ? 'checkbox' : 'square-outline'}
                      size={20}
                      color={checked ? colors.accent : colors.textSubtle}
                    />
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
                  </Pressable>
                );
              })}
            </View>

            {selected.length > 0 ? (
              <View className="gap-2">
                <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                  2 · Who?
                </Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                  <View className="flex-row gap-2 pr-4">
                    <StaffChip
                      label="Anyone"
                      caption={bookable.length > 0 ? `${bookable.length} available` : 'next free'}
                      picked={staffId === null}
                      onPress={() => setStaffId(null)}
                    />
                    {bookable.map((member) => (
                      <StaffChip
                        key={member.id}
                        label={member.name}
                        caption={member.is_placeholder ? 'at this shop' : 'available today'}
                        picked={staffId === member.id}
                        onPress={() => setStaffId(member.id)}
                      />
                    ))}
                  </View>
                </ScrollView>
              </View>
            ) : null}

            {selected.length > 0 ? (
              <View className="gap-2">
                <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                  3 · When?
                </Text>
                {freeSlots.length === 0 ? (
                  <View className="gap-2">
                    <Text className="text-sm" style={{ color: colors.textMuted }}>
                      Nothing free in the next week. You can wait to be told when
                      something is cancelled.
                    </Text>
                    {onWaitlist ? (
                      <Text className="text-sm font-medium" style={{ color: colors.success }}>
                        Added. We will offer you the next cancellation.
                      </Text>
                    ) : (
                      <Button
                        variant="ghost"
                        onPress={() => void addToWaitlist()}
                        loading={joinWaitlist.isPending}
                        testID="join-waitlist">
                        Join the waitlist
                      </Button>
                    )}
                  </View>
                ) : (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                    <View className="flex-row gap-2 pr-4">
                      {freeSlots.slice(0, 24).map((entry) => {
                        const picked = slot === entry.starts_at;
                        return (
                          <Pressable
                            key={entry.starts_at}
                            onPress={() => void chooseTime(entry.starts_at)}
                            accessibilityRole="radio"
                            accessibilityState={{ selected: picked }}
                            className="rounded-2xl border px-3 py-2.5"
                            style={{
                              backgroundColor: picked ? colors.accent : colors.surface,
                              borderColor: picked ? colors.accent : colors.border,
                            }}>
                            <Text
                              className="text-xs font-semibold"
                              style={{ color: picked ? colors.accentText : colors.text }}>
                              {formatWhen(entry.starts_at)}
                            </Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  </ScrollView>
                )}
              </View>
            ) : null}

            {priced ? (
              <View className="gap-2">
                <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                  3 · What it costs
                </Text>
                <View className="rounded-2xl border p-4" style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
                  {priced.items.map((line, index) => (
                    <View key={line.service_id}>
                      {index > 0 ? <Divider className="my-2" /> : null}
                      <View className="flex-row justify-between">
                        <Text className="text-sm" style={{ color: colors.textMuted }}>
                          {line.name}
                        </Text>
                        <Text className="text-sm" style={{ color: colors.text }}>
                          {line.unit_price_display}
                        </Text>
                      </View>
                    </View>
                  ))}

                  <Divider className="my-3" />

                  <View className="flex-row justify-between">
                    <Text className="text-sm" style={{ color: colors.textMuted }}>
                      Service fee
                    </Text>
                    <Text className="text-sm" style={{ color: colors.textMuted }}>
                      {priced.platform_fee_display}
                    </Text>
                  </View>

                  {priced.deposit > 0 ? (
                    <>
                      <View className="mt-2 flex-row justify-between">
                        <View className="flex-1 pr-3">
                          <Text className="text-sm" style={{ color: colors.textMuted }}>
                            Due now
                          </Text>
                          <Text className="text-xs" style={{ color: colors.textSubtle }}>
                            {priced.deposit_percent}% secures your slot
                          </Text>
                        </View>
                        <Text className="text-sm font-medium" style={{ color: colors.text }}>
                          {priced.deposit_display}
                        </Text>
                      </View>

                      <View className="mt-2 flex-row justify-between">
                        <View className="flex-1 pr-3">
                          <Text className="text-sm" style={{ color: colors.textMuted }}>
                            Due at the shop
                          </Text>
                          <Text className="text-xs" style={{ color: colors.textSubtle }}>
                            Pay the rest in cash or card when you arrive
                          </Text>
                        </View>
                        <Text className="text-sm font-medium" style={{ color: colors.text }}>
                          {priced.balance_display}
                        </Text>
                      </View>
                    </>
                  ) : null}

                  <View className="mt-2 flex-row justify-between">
                    <Text className="text-base font-semibold" style={{ color: colors.text }}>
                      Total
                    </Text>
                    <Text className="text-base font-semibold" style={{ color: colors.text }}>
                      {priced.total_display}
                    </Text>
                  </View>

                  {priced.promo_code ? (
                    <View className="mt-2 flex-row justify-between">
                      <View className="flex-1 pr-3">
                        <Text className="text-sm" style={{ color: colors.success }}>
                          {priced.promo_description || `Code ${priced.promo_code} applied`}
                        </Text>
                      </View>
                      <Text className="text-sm font-medium" style={{ color: colors.success }}>
                        applied
                      </Text>
                    </View>
                  ) : null}

                  {priced.points_spent > 0 ? (
                    <View className="mt-2 flex-row justify-between">
                      <View className="flex-1 pr-3">
                        <Text className="text-sm" style={{ color: colors.success }}>
                          {priced.points_spent} points
                        </Text>
                        <Text className="text-xs" style={{ color: colors.textSubtle }}>
                          Off what you pay today
                        </Text>
                      </View>
                      <Text className="text-sm font-medium" style={{ color: colors.success }}>
                        {formatPaise(priced.points_worth_minor)}
                      </Text>
                    </View>
                  ) : null}

                  {priced.risk?.risk_level ? (
                    <View
                      className="mt-2 rounded-xl px-3 py-2"
                      style={{ backgroundColor: `${colors.warning}14` }}
                      testID="risk-advisory">
                      <Text className="text-xs font-semibold" style={{ color: colors.warning }}>
                        Worth a deposit this time
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textMuted }}>
                        {priced.risk.no_shows} of {priced.risk.no_shows + priced.risk.completed}{' '}
                        appointments not turned up to. You can take a larger deposit to
                        secure the slot — the price below does not change on its own.
                      </Text>
                    </View>
                  ) : null}

                  {cancellationNote(priced) ? (
                    <Text className="mt-3 text-xs leading-4" style={{ color: colors.textSubtle }}>
                      {cancellationNote(priced)}
                    </Text>
                  ) : null}

                  {!priced.is_available ? (
                    <Text className="mt-2 text-xs font-medium" style={{ color: colors.danger }}>
                      That slot was just taken. Pick another.
                    </Text>
                  ) : null}
                </View>
              </View>
            ) : null}

            {questions.length > 0 ? (
              <View className="gap-2">
                <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                  4 · Before we start
                </Text>
                {prompt.data?.forms.map((form) =>
                  form.description ? (
                    <Text key={form.id} className="text-xs" style={{ color: colors.textSubtle }}>
                      {form.description}
                    </Text>
                  ) : null,
                )}
                {questions.map((question) => (
                  <ConsultationQuestionField
                    key={question.id}
                    question={question}
                    value={answers[question.id] ?? ''}
                    onChange={(next) => setAnswers((current) => ({ ...current, [question.id]: next }))}
                  />
                ))}
              </View>
            ) : null}

            {priced ? (
              <View className="gap-3">
                <View className="gap-2">
                  <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                    5 · Regular visits
                  </Text>
                  <Pressable
                    onPress={() => setRepeat(!repeat)}
                    accessibilityRole="switch"
                    accessibilityState={{ checked: repeat }}
                    testID="repeat-toggle"
                    className="flex-row items-center justify-between rounded-2xl border px-4 py-3"
                    style={{
                      backgroundColor: repeat ? `${colors.accent}12` : colors.surface,
                      borderColor: repeat ? colors.accent : colors.border,
                    }}>
                    <View className="flex-1 pr-3">
                      <Text className="text-sm font-medium" style={{ color: colors.text }}>
                        Make this a regular
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textSubtle }}>
                        Book several visits now. Each is paid for on its own, and you
                        can cancel any one of them on its own.
                      </Text>
                    </View>
                    <Ionicons
                      name={repeat ? 'checkbox' : 'square-outline'}
                      size={20}
                      color={repeat ? colors.accent : colors.textSubtle}
                    />
                  </Pressable>

                  {!repeat ? (
                    <Field
                      label="Got a referral code?"
                      placeholder="Optional"
                      value={referralCode}
                      onChangeText={setReferralCode}
                      autoCapitalize="characters"
                      autoCorrect={false}
                      hint="If somebody sent you one, adding it here credits them when your appointment is done."
                      testID="referral-code"
                    />
                  ) : null}

                  {repeat ? (
                    <>
                      <View className="flex-row gap-2">
                        {INTERVALS.map((option) => (
                          <Pressable
                            key={option.days}
                            onPress={() => setIntervalDays(option.days)}
                            accessibilityRole="radio"
                            accessibilityState={{ selected: intervalDays === option.days }}
                            testID={`interval-${option.days}`}>
                            <View
                              className="rounded-full px-3 py-1.5"
                              style={{
                                backgroundColor:
                                  intervalDays === option.days ? colors.accent : colors.surface,
                              }}>
                              <Text
                                className="text-xs font-medium"
                                style={{
                                  color:
                                    intervalDays === option.days
                                      ? colors.accentText
                                      : colors.textMuted,
                                }}>
                                {option.label}
                              </Text>
                            </View>
                          </Pressable>
                        ))}
                      </View>

                      <View className="flex-row gap-2">
                        {VISIT_COUNTS.map((count) => (
                          <Pressable
                            key={count}
                            onPress={() => setVisitCount(count)}
                            accessibilityRole="radio"
                            accessibilityState={{ selected: visitCount === count }}
                            testID={`visits-${count}`}>
                            <View
                              className="rounded-full px-3 py-1.5"
                              style={{
                                backgroundColor:
                                  visitCount === count ? colors.accent : colors.surface,
                              }}>
                              <Text
                                className="text-xs font-medium"
                                style={{
                                  color:
                                    visitCount === count ? colors.accentText : colors.textMuted,
                                }}>
                                {count} visits
                              </Text>
                            </View>
                          </Pressable>
                        ))}
                      </View>

                      <Text className="text-xs leading-4" style={{ color: colors.textSubtle }}>
                        {visitCount} visits, every {intervalDays} days, starting{' '}
                        {formatWhen(slot as string)}. Each one is booked separately and
                        charged separately.
                      </Text>
                    </>
                  ) : null}
                </View>

                <View className="gap-2">
                  <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                    6 · Discounts
                  </Text>
                  <View className="flex-row items-end gap-2">
                    <View className="flex-1">
                      <Field
                        label="Promo code"
                        placeholder="Have a code?"
                        value={promoCode}
                        onChangeText={setPromoCode}
                        autoCapitalize="characters"
                        testID="promo-code"
                      />
                    </View>
                    <Button
                      variant="secondary"
                      onPress={() => void applyPromo()}
                      loading={quote.isPending}
                      testID="promo-apply">
                      Apply
                    </Button>
                  </View>
                </View>

                {points.data && points.data.available > 0 ? (
                  <Pressable
                    onPress={() => void togglePoints()}
                    accessibilityRole="switch"
                    accessibilityState={{ checked: redeemPoints }}
                    testID="points-toggle"
                    className="flex-row items-center justify-between rounded-2xl border px-4 py-3"
                    style={{
                      backgroundColor: redeemPoints ? `${colors.accent}12` : colors.surface,
                      borderColor: redeemPoints ? colors.accent : colors.border,
                    }}>
                    <View className="flex-1 pr-3">
                      <Text className="text-sm font-medium" style={{ color: colors.text }}>
                        Use my {points.data.available} points
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textSubtle }}>
                        Worth {formatPaise(points.data.worth_minor)} off
                        {points.data.expiring_soon > 0
                          ? ` · ${points.data.expiring_soon} expiring soon`
                          : ''}
                      </Text>
                    </View>
                    <Ionicons
                      name={redeemPoints ? 'checkbox' : 'square-outline'}
                      size={20}
                      color={redeemPoints ? colors.accent : colors.textSubtle}
                    />
                  </Pressable>
                ) : null}

                <FormError message={error} />
              </View>
            ) : null}
          </ScrollView>

          <View className="border-t px-5 py-4" style={{ borderTopColor: colors.border }}>
            <Button
              onPress={confirm}
              disabled={!slot || !priced || !priced.is_available || missingRequired > 0}
              loading={create.isPending}
              testID="book-confirm">
              {priced
                ? priced.deposit > 0
                  ? `Pay ${priced.deposit_display} to confirm`
                  : `Confirm · ${priced.total_display}`
                : 'Confirm booking'}
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}
function StaffChip({
  label,
  caption,
  picked,
  onPress,
}: {
  label: string;
  caption: string;
  picked: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ selected: picked }}
      testID={`staff-chip-${label}`}
      className="rounded-2xl border px-3 py-2.5"
      style={{
        backgroundColor: picked ? colors.accent : colors.surface,
        borderColor: picked ? colors.accent : colors.border,
      }}>
      <Text
        className="text-sm font-semibold"
        style={{ color: picked ? colors.accentText : colors.text }}>
        {label}
      </Text>
      <Text
        className="text-xs"
        style={{ color: picked ? colors.accentText : colors.textSubtle }}>
        {caption}
      </Text>
    </Pressable>
  );
}


/**
 * One consultation question, rendered by what was asked.
 *
 * A yes/no is two taps and a choice is a list; neither should be a keyboard. A
 * barber asking "have you had colour before" wants an answer they can read at
 * a glance down a column of clients, not a paragraph.
 */
function ConsultationQuestionField({
  question,
  value,
  onChange,
}: {
  question: ConsultationQuestion;
  value: string;
  onChange: (next: string) => void;
}) {
  const colors = useColors();

  if (question.kind === 'yes_no') {
    return (
      <View className="gap-2">
        <Text className="text-sm font-medium" style={{ color: colors.text }}>
          {question.label}
          {question.is_required ? ' *' : ''}
        </Text>
        <View className="flex-row gap-2">
          {['yes', 'no'].map((option) => (
            <Pressable
              key={option}
              onPress={() => onChange(option)}
              accessibilityRole="radio"
              accessibilityState={{ selected: value === option }}
              testID={`question-${question.id}-${option}`}>
              <View
                className="rounded-full px-4 py-2"
                style={{ backgroundColor: value === option ? colors.accent : colors.surface }}>
                <Text
                  className="text-sm font-medium"
                  style={{ color: value === option ? colors.accentText : colors.text }}>
                  {option === 'yes' ? 'Yes' : 'No'}
                </Text>
              </View>
            </Pressable>
          ))}
        </View>
      </View>
    );
  }

  if (question.kind === 'choice') {
    return (
      <View className="gap-2">
        <Text className="text-sm font-medium" style={{ color: colors.text }}>
          {question.label}
          {question.is_required ? ' *' : ''}
        </Text>
        <View className="gap-2">
          {question.choices.map((option) => (
            <Pressable
              key={option}
              onPress={() => onChange(option)}
              accessibilityRole="radio"
              accessibilityState={{ selected: value === option }}
              testID={`question-${question.id}-choice-${option}`}
              className="rounded-2xl border px-4 py-2.5"
              style={{
                backgroundColor: value === option ? `${colors.accent}12` : colors.surface,
                borderColor: value === option ? colors.accent : colors.border,
              }}>
              <Text className="text-sm" style={{ color: colors.text }}>
                {option}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>
    );
  }

  return (
    <View className="gap-1">
      <Field
        label={question.label}
        hint={question.help_text}
        placeholder={question.is_required ? 'Needed to book you in' : 'Optional'}
        value={value}
        onChangeText={onChange}
        multiline={question.kind === 'long_text'}
        numberOfLines={question.kind === 'long_text' ? 3 : 1}
        testID={`question-${question.id}`}
      />
    </View>
  );
}
