import { useMemo, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useAvailability, useMyShop, useSaveShop } from '@/api/hooks';
import { Button, Card, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';

/**
 * Opening hours and slot length.
 *
 * Slot length is the promise the shop actually makes: it divides the day into
 * bookable blocks and sets how long one holds. Too short and the app sells more
 * time than the shop has; too long and the shop looks closed for most of the day.
 */
export default function AvailabilityScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const shop = useMyShop();
  const save = useSaveShop();
  const availability = useAvailability(shop.data?.id ?? null, 14);

  const [opening, setOpening] = useState(shop.data?.opening_time ?? '09:00');
  const [closing, setClosing] = useState(shop.data?.closing_time ?? '20:00');
  const [interval, setIntervalValue] = useState(
    String(shop.data?.slot_interval_minutes ?? 30),
  );
  const [error, setError] = useState<string | null>(null);

  const slots = useMemo(() => availability.data?.slots ?? [], [availability.data]);
  const free = slots.filter((slot) => slot.is_available).length;

  async function submit() {
    setError(null);

    const minutes = Number(interval);
    if (!Number.isFinite(minutes) || minutes < 5 || minutes > 240) {
      setError('Slot length has to be between 5 and 240 minutes.');
      return;
    }
    if (closing.trim() <= opening.trim()) {
      setError('Closing time has to be after opening time.');
      return;
    }

    try {
      await save.mutateAsync({
        opening_time: opening.trim(),
        closing_time: closing.trim(),
        slot_interval_minutes: minutes,
      });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not save your hours.'));
    }
  }

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

        <Button onPress={submit} loading={save.isPending} testID="hours-save">
          Save hours
        </Button>
      </Card>

      <Card className="gap-1">
        <Text className="text-sm font-semibold" style={{ color: colors.text }}>
          Next 14 days
        </Text>
        {availability.isLoading ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Checking the calendar…
          </Text>
        ) : slots.length === 0 ? (
          <EmptyState
            icon="calendar-outline"
            title="Nothing bookable"
            body="Your day may be shorter than one slot. Try a longer day or a shorter slot."
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