import { useMemo, useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useCreateBooking, useQuote, useShopStaff } from '@/api/hooks';
import { Button, Divider, useColors } from '@/components/ui';
import { formatWhen } from '@/components/booking-row';
import { cancellationNote } from '@/lib/money';
import type { Availability, ProviderDetail, Service } from '@/types/api';

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

  const quote = useQuote();
  const create = useCreateBooking();
  const staff = useShopStaff(provider.id);

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
  }

  async function chooseTime(startsAt: string) {
    setError(null);
    setSlot(startsAt);
    try {
      await quote.mutateAsync({
        provider: provider.id,
        services: selected.map((service) => service.id),
        starts_at: startsAt,
      });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not price that slot.'));
    }
  }

  async function confirm() {
    if (!slot) return;
    setError(null);
    try {
      const booking = await create.mutateAsync({
        provider: provider.id,
        services: selected.map((service) => service.id),
        starts_at: slot,
        ...(staffId ? { staff: staffId } : {}),
      });
      onClose();
      router.replace(`/(customer)/booking/${booking.reference}`);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not book that slot.'));
    }
  }

  const priced = quote.data;

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
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    Nothing free in the next week. Try another shop.
                  </Text>
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

            {error ? (
              <Text className="text-sm" style={{ color: colors.danger }}>
                {error}
              </Text>
            ) : null}
          </ScrollView>

          <View className="border-t px-5 py-4" style={{ borderTopColor: colors.border }}>
            <Button
              onPress={confirm}
              disabled={!slot || !priced || !priced.is_available}
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
