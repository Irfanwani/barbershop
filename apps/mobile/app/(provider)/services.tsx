import { useState } from 'react';
import { FlatList, Modal, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError } from '@/api/client';
import {
  useCreateService,
  useDeleteService,
  useMyServices,
  useUpdateService,
} from '@/api/hooks';
import { Badge, Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import type { Service } from '@/types/api';

/**
 * The provider's menu.
 *
 * Customers book by service, so this list *is* the shop's bookability. A service
 * marked inactive disappears from search and from the booking screen but stays on
 * past bookings — deleting it outright would rewrite what someone was charged.
 */
export default function ProviderServices() {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  const services = useMyServices();
  const remove = useDeleteService();

  const [editing, setEditing] = useState<Service | 'new' | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function onRefresh() {
    setRefreshing(true);
    await services.refetch();
    setRefreshing(false);
  }

  const rows = services.data ?? [];

  return (
    <View className="flex-1" style={{ backgroundColor: colors.background }}>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{
          paddingTop: insets.top + 8,
          paddingBottom: insets.bottom + 24,
          gap: 12,
          paddingHorizontal: 16,
        }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        ListHeaderComponent={
          <View className="flex-row items-center justify-between pb-2">
            <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
              Menu
            </Text>
            <Button onPress={() => setEditing('new')} testID="service-add">
              Add
            </Button>
          </View>
        }
        renderItem={({ item }) => (
          <Card className="gap-3">
            <View className="flex-row items-start justify-between gap-3">
              <View className="flex-1">
                <Text className="text-base font-semibold" style={{ color: colors.text }}>
                  {item.name}
                </Text>
                <Text className="text-xs" style={{ color: colors.textMuted }}>
                  {item.duration_minutes} min
                </Text>
              </View>
              <View className="items-end gap-1">
                <Text className="text-base font-semibold" style={{ color: colors.text }}>
                  {item.price_display}
                </Text>
                {item.is_active ? null : <Badge tone="danger">Hidden</Badge>}
              </View>
            </View>

            <View className="flex-row gap-2">
              <Button
                variant="secondary"
                className="flex-1"
                onPress={() => setEditing(item)}
                testID={`service-edit-${item.id}`}>
                Edit
              </Button>
              <Button
                variant="ghost"
                accessibilityLabel="Remove service"
                icon="trash-outline"
                onPress={() => remove.mutate(item.id)}
                loading={remove.isPending && remove.variables === item.id}
                testID={`service-delete-${item.id}`}
              />
            </View>
          </Card>
        )}
        ListEmptyComponent={
          services.isLoading ? null : (
            <EmptyState
              icon="pricetag-outline"
              title="No services yet"
              body="Customers can only book what is on this list. Add your first one."
              action={<Button onPress={() => setEditing('new')}>Add a service</Button>}
            />
          )
        }
      />

      {remove.isError ? (
        <View className="px-4 pb-4">
          <Card>
            <Text className="text-sm" style={{ color: colors.danger }}>
              {errorMessage(remove.error, 'Could not remove that service.')}
            </Text>
          </Card>
        </View>
      ) : null}

      <ServiceEditor
        visible={editing !== null}
        service={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
      />
    </View>
  );
}

function ServiceEditor({
  visible,
  service,
  onClose,
}: {
  visible: boolean;
  service: Service | null;
  onClose: () => void;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const create = useCreateService();
  const update = useUpdateService();

  const [name, setName] = useState(service?.name ?? '');
  const [price, setPrice] = useState(service ? String(service.price / 100) : '');
  const [duration, setDuration] = useState(String(service?.duration_minutes ?? 30));
  const [active, setActive] = useState(service?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);

  // Re-seed the form when a different service is opened.
  const [seededFor, setSeededFor] = useState<Service | 'closed'>('closed');
  if (visible && seededFor !== (service ?? 'closed')) {
    setName(service?.name ?? '');
    setPrice(service ? String(service.price / 100) : '');
    setDuration(String(service?.duration_minutes ?? 30));
    setActive(service?.is_active ?? true);
    setError(null);
    setSeededFor(service ?? 'closed');
  }
  if (!visible && seededFor !== 'closed') setSeededFor('closed');

  async function save() {
    setError(null);

    const rupees = Number(price.trim());
    if (!name.trim()) return setError('Give the service a name.');
    if (!Number.isFinite(rupees) || rupees <= 0) return setError('Enter a price in rupees.');
    if (rupees > 100_000) return setError('That looks too high. Check the amount.');

    const body = {
      name: name.trim(),
      price: Math.round(rupees * 100),
      duration_minutes: Math.max(5, Number(duration.trim()) || 30),
      is_active: active,
    };

    try {
      if (service) await update.mutateAsync({ id: service.id, body });
      else await create.mutateAsync(body);
      onClose();
    } catch (caught) {
      // Show the server's complaint about the name if there is one; it is the
      // field most likely to be rejected (duplicate), and the one the user can
      // act on without guessing.
      const nameError = isApiError(caught) ? caught.fieldErrors.name?.[0] : undefined;
      setError(nameError ?? errorMessage(caught, 'Could not save that service.'));
    }
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View className="flex-1 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
        <View
          className="max-h-[85%] rounded-t-3xl"
          style={{ backgroundColor: colors.background, paddingBottom: insets.bottom }}>
          <View
            className="flex-row items-center justify-between px-5 py-4"
            style={{ borderBottomColor: colors.border, borderBottomWidth: 1 }}>
            <Text className="text-lg font-semibold" style={{ color: colors.text }}>
              {service ? 'Edit service' : 'New service'}
            </Text>
            <IconButton name="close" label="Close" onPress={onClose} />
          </View>

          <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }}>
            <FormError message={error} />

            <Field
              label="Name"
              placeholder="Haircut"
              value={name}
              onChangeText={setName}
              testID="editor-name"
            />

            <View className="flex-row gap-3">
              <View className="flex-1">
                <Field
                  label="Price (₹)"
                  keyboardType="numeric"
                  value={price}
                  onChangeText={setPrice}
                  testID="editor-price"
                />
              </View>
              <View className="flex-1">
                <Field
                  label="Minutes"
                  keyboardType="numeric"
                  value={duration}
                  onChangeText={setDuration}
                  testID="editor-duration"
                />
              </View>
            </View>

            <Pressable
              onPress={() => setActive((current) => !current)}
              accessibilityRole="switch"
              accessibilityState={{ checked: active }}
              accessibilityLabel="Show this service"
              testID="editor-active"
              className="flex-row items-center justify-between rounded-2xl border px-4 py-3"
              style={{ backgroundColor: colors.surface, borderColor: colors.border }}>
              <View className="flex-1 pr-3">
                <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                  Show in search
                </Text>
                <Text className="text-xs" style={{ color: colors.textSubtle }}>
                  Hidden services keep existing bookings but cannot be booked again.
                </Text>
              </View>
              <Ionicons
                name={active ? 'eye-outline' : 'eye-off-outline'}
                size={20}
                color={active ? colors.accent : colors.textSubtle}
              />
            </Pressable>

            <Divider />
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              Bookings already made keep the price they were made at. Changing this
              only affects future bookings.
            </Text>
          </ScrollView>

          <View className="border-t px-5 py-4" style={{ borderTopColor: colors.border }}>
            <Button
              onPress={save}
              loading={create.isPending || update.isPending}
              testID="editor-save">
              {service ? 'Save changes' : 'Add to menu'}
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}