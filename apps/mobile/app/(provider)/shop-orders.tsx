import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useOrderAction, useShopOrders } from '@/api/hooks';
import { Badge, Button, Card, Divider, EmptyState, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import type { ProductOrder } from '@/types/api';

const TABS = [
  { key: 'paid', label: 'To prepare' },
  { key: 'ready', label: 'Ready' },
  { key: 'collected', label: 'Collected' },
  { key: 'all', label: 'All' },
];

/**
 * Product orders for this shop.
 *
 * Fulfilment is collection, so the useful question is not "what is paid" but
 * "what is waiting to be picked up". Paid and ready are separate tabs for that
 * reason: someone standing at the counter needs the second one.
 */
export default function ShopOrdersScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [tab, setTab] = useState('paid');
  const orders = useShopOrders(tab === 'all' ? {} : { status: tab });
  const act = useOrderAction();
  const [error, setError] = useState<string | null>(null);

  async function move(order: ProductOrder, action: 'ready' | 'collect') {
    setError(null);
    try {
      await act.mutateAsync({ reference: order.reference, action });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not update that order.'));
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
      <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
        Product orders
      </Text>

      <View className="flex-row gap-2">
        {TABS.map((entry) => {
          const active = entry.key === tab;
          return (
            <Pressable
              key={entry.key}
              onPress={() => setTab(entry.key)}
              accessibilityRole="button"
              accessibilityLabel={entry.label}
              accessibilityState={{ selected: active }}
              className="rounded-full border px-3 py-1.5 active:opacity-70"
              style={{
                backgroundColor: active ? colors.accent : colors.surface,
                borderColor: active ? colors.accent : colors.border,
              }}>
              <Text
                className="text-xs font-semibold"
                style={{ color: active ? colors.accentText : colors.textMuted }}>
                {entry.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <FormError message={error} />

      {orders.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Loading orders…
        </Text>
      ) : (orders.data?.results.length ?? 0) === 0 ? (
        <EmptyState
          icon="bag-handle-outline"
          title="Nothing here"
          body="Product orders for this shop will appear here."
        />
      ) : (
        orders.data?.results.map((order) => (
          <Card key={order.reference} className="gap-3">
            <View className="flex-row items-center justify-between gap-3">
              <View className="flex-1">
                <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
                  {order.reference}
                </Text>
                <Text className="text-xs" style={{ color: colors.textSubtle }}>
                  {new Date(order.created_at).toLocaleDateString()}
                </Text>
              </View>
              <Badge
                tone={
                  order.status === 'collected'
                    ? 'success'
                    : order.status === 'cancelled'
                      ? 'danger'
                      : 'warning'
                }>
                {order.status}
              </Badge>
            </View>

            <View>
              {order.lines.map((line) => (
                <View key={line.product} className="flex-row items-center gap-2 py-0.5">
                  <Ionicons name="cube-outline" size={14} color={colors.textSubtle} />
                  <Text className="flex-1 text-sm" style={{ color: colors.text }}>
                    {line.name}
                  </Text>
                  <Text className="text-sm" style={{ color: colors.textMuted }}>
                    ×{line.quantity}
                  </Text>
                </View>
              ))}
            </View>

            <Divider />

            <View className="flex-row items-center justify-between gap-3">
              <Text className="text-base font-bold" style={{ color: colors.text }}>
                {order.total_display}
              </Text>
              <View className="flex-row gap-2">
                {order.status === 'paid' ? (
                  <Button onPress={() => move(order, 'ready')} testID={`ready-${order.reference}`}>
                    Ready
                  </Button>
                ) : null}
                {order.status === 'ready' ? (
                  <Button
                    onPress={() => move(order, 'collect')}
                    testID={`collect-${order.reference}`}>
                    Collected
                  </Button>
                ) : null}
                {order.can_be_paid || order.status === 'ready' ? (
                  <Button variant="ghost" onPress={() => router.push(`/orders/${order.reference}`)}>
                    View
                  </Button>
                ) : null}
              </View>
            </View>
          </Card>
        ))
      )}
    </ScrollView>
  );
}