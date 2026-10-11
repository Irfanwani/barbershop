import { useEffect, useMemo, useState } from 'react';
import { ScrollView, Switch, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';

import { errorMessage } from '@/api/client';
import {
  useAvailability,
  useMyHours,
  useMyShop,
  useSaveHours,
  useSaveShop,
  useSetAcceptingBookings,
} from '@/api/hooks';
import { Button, Card, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import {
  buildWeek,
  openDayCount,
  toApiDays,
  validateWeek,
  WEEKDAY_NAMES,
  type DayDraft,
} from '@/lib/weekdays';

/**
 * Opening hours, slot length, and the bookings switch.
 *
 * Slot length is the promise the shop actually makes: it divides the day into
 * bookable blocks and sets how long one holds. Too short and the app sells more
 * time than the shop has; too long and the shop looks shut for most of the day.
 */
export default function AvailabilityScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const shop = useMyShop();
  const hours = useMyHours();
  const save = useSaveShop();
  const saveHours = useSaveHours();
  const setAccepting = useSetAcceptingBookings();
  const availability = useAvailability(shop.data?.id ?? null, 14);

  const [opening, setOpening] = useState(shop.data?.opening_time ?? '09:00');
  const [closing, setClosing] = useState(shop.data?.closing_time ?? '20:00');
  const [interval, setIntervalValue] = useState(
    String(shop.data?.slot_interval_minutes ?? 30),
  );
  const [days, setDays] = useState<DayDraft[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const acceptingBookings = shop.data?.is_accepting_bookings ?? true;

  // Seed the week once, from whatever the server has. Kept in local state so a
  // half-typed time is not written to the server on every keystroke.
  useEffect(() => {
    if (days !== null || !shop.data) return;
    setDays(
      buildWeek(hours.data, {
        opening_time: shop.data?.opening_time ?? '09:00',
        closing_time: shop.data?.closing_time ?? '20:00',
      }),
    );
  }, [days, hours.data, shop.data]);

  const slots = useMemo(() => availability.data?.slots ?? [], [availability.data]);
  const free = slots.filter((slot) => slot.is_available).length;
  const openDays = days ? openDayCount(days) : 0;

  function patchDay(weekday: number, patch: Partial<DayDraft>) {
    setDays((current) =>
      current?.map((day) => (day.weekday === weekday ? { ...day, ...patch } : day)) ?? current,
    );
  }

  async function submit() {
    setError(null);

    const minutes = Number(interval);
    if (!Number.isFinite(minutes) || minutes < 5 || minutes > 240) {
      setError('Slot length has to be between 5 and 240 minutes.');
      return;
    }
    const problem = validateWeek(days ?? [], opening, closing);
    if (problem) {
      setError(problem);
      return;
    }

    try {
      await save.mutateAsync({
        opening_time: opening.trim(),
        closing_time: closing.trim(),
        slot_interval_minutes: minutes,
      });
      await saveHours.mutateAsync(toApiDays(days ?? []));
    } catch (caught) {
      setError(errorMessage(caught, 'Could not save your hours.'));
    }
  }

  async function toggleBookings(next: boolean) {
    setError(null);
    try {
      await setAccepting.mutateAsync(next);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not change that.'));
    }
  }

  const saving = save.isPending || saveHours.isPending;

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}
      keyboardShouldPersistTaps="handled">
      <IconButton
        name="arrow-back"
        label="Back"
        onPress={() => router.back()}
        className="self-start"
      />

      <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
        Availability
      </Text>

      <FormError message={error} />

      <Card className="gap-3">
        <View className="flex-row items-start gap-3">
          <View className="flex-1 gap-1.5">
            <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
              Open for bookings
            </Text>
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              Turning this off hides you from search and stops new bookings. Appointments
              already taken are kept.
            </Text>
          </View>
          <Switch
            value={acceptingBookings}
            onValueChange={toggleBookings}
            disabled={setAccepting.isPending}
            trackColor={{ true: colors.accent, false: colors.border }}
            accessibilityLabel="Open for bookings"
            testID="availability-accepting-toggle"
          />
        </View>
        {!acceptingBookings ? (
          <View className="flex-row items-center gap-2">
            <Ionicons name="pause-circle-outline" size={16} color={colors.warning} />
            <Text className="text-xs" style={{ color: colors.warning }}>
              Closed. Customers cannot book you right now.
            </Text>
          </View>
        ) : null}
      </Card>

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Default hours
        </Text>
        <Card className="gap-3">
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Field
                label="Opens"
                placeholder="09:00"
                value={opening}
                onChangeText={setOpening}
                testID="hours-opening"
              />
            </View>
            <View className="flex-1">
              <Field
                label="Closes"
                placeholder="20:00"
                value={closing}
                onChangeText={setClosing}
                testID="hours-closing"
              />
            </View>
          </View>

          <Field
            label="Slot length (minutes)"
            placeholder="30"
            keyboardType="numeric"
            value={interval}
            onChangeText={setIntervalValue}
            hint="How long one appointment holds."
            testID="hours-interval"
          />
        </Card>
      </View>

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Your week
        </Text>
        <Card>
          {days === null ? (
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              Loading…
            </Text>
          ) : (
            days.map((day, index) => (
              <View key={day.weekday}>
                {index > 0 ? (
                  <View className="my-3 h-px" style={{ backgroundColor: colors.border }} />
                ) : null}
                <View className="flex-row items-center justify-between gap-3">
                  <Text
                    className="w-24 text-[15px] font-medium"
                    style={{ color: colors.text }}>
                    {WEEKDAY_NAMES[day.weekday]}
                  </Text>
                  <Switch
                    value={!day.isClosed}
                    onValueChange={(open) => patchDay(day.weekday, { isClosed: !open })}
                    trackColor={{ true: colors.accent, false: colors.border }}
                    accessibilityLabel={`${WEEKDAY_NAMES[day.weekday]} open`}
                    testID={`day-toggle-${day.weekday}`}
                  />
                </View>

                {!day.isClosed ? (
                  <View className="mt-3 flex-row gap-3">
                    <View className="flex-1">
                      <Field
                        label="Opens"
                        placeholder="09:00"
                        value={day.opensAt}
                        onChangeText={(value) => patchDay(day.weekday, { opensAt: value })}
                        testID={`day-opens-${day.weekday}`}
                      />
                    </View>
                    <View className="flex-1">
                      <Field
                        label="Closes"
                        placeholder="20:00"
                        value={day.closesAt}
                        onChangeText={(value) => patchDay(day.weekday, { closesAt: value })}
                        testID={`day-closes-${day.weekday}`}
                      />
                    </View>
                  </View>
                ) : null}
              </View>
            ))
          )}
        </Card>
      </View>

      <Button onPress={submit} loading={saving} testID="hours-save">
        Save hours
      </Button>

      <Card className="gap-1">
        <Text className="text-sm font-semibold" style={{ color: colors.text }}>
          Next 14 days
        </Text>
        {availability.isLoading ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Checking the calendar…
          </Text>
        ) : !acceptingBookings ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            You are closed, so nothing is being offered. Your existing appointments are
            unaffected.
          </Text>
        ) : slots.length === 0 ? (
          <EmptyState
            icon="calendar-outline"
            title="Nothing bookable"
            body={
              openDays === 0
                ? 'Every day is switched off. Turn at least one day on.'
                : 'Your day may be shorter than one slot. Try a longer day or a shorter slot.'
            }
          />
        ) : (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {free} of {slots.length} slots are free.
          </Text>
        )}
      </Card>
    </ScrollView>
  );
}