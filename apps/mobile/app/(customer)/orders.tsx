import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useMyOrders } from '@/api/hooks';
import { Badge, Button, Card, EmptyState, useColors } from '@/components/ui';
import type { OrderStatus, ProductOrder } from '@/types/api';

const FILTERS: { key: string; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'To pay' },
  { key: 'ready', label: 'Ready' },
  { key: 'collected', label: 'Collected' },
];

function toneFor(status: OrderStatus): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'collected') return 'success';
  if (status === 'cancelled') return 'danger';
  if (status === 'pending') return 'warning';
  return 'neutral';
}

/** Everything bought, and how far along each order is. */
export default function OrdersScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [status, setStatus] = useState('all');
  const orders = useMyOrders(status === 'all' ? {} : { status });

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
      <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
        Orders
      </Text>

      <View className="flex-row gap-2">
        {FILTERS.map((filter) => {
          const active = filter.key === status;
          return (
            <Pressable
              key={filter.key}
              onPress={() => setStatus(filter.key)}
              accessibilityRole="button"
              accessibilityLabel={filter.label}
              accessibilityState={{ selected: active }}
              className="rounded-full border px-3 py-1.5 active:opacity-70"
              style={{
                backgroundColor: active ? colors.accent : colors.surface,
                borderColor: active ? colors.accent : colors.border,
              }}>
              <Text
                className="text-xs font-semibold"
                style={{ color: active ? colors.accentText : colors.textMuted }}>
                {filter.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {orders.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Loading your orders…
        </Text>
      ) : (orders.data?.results.length ?? 0) === 0 ? (
        <EmptyState
          icon="bag-handle-outline"
          title="Nothing here yet"
          body="Products you buy from a shop will show up here."
          action={
            <Button onPress={() => router.push('/(customer)/home')}>Find a shop</Button>
          }
        />
      ) : (
        orders.data?.results.map((order) => <OrderCard key={order.reference} order={order} />)
      )}
    </ScrollView>
  );
}

function OrderCard({ order }: { order: ProductOrder }) {
  const colors = useColors();
  const router = useRouter();

  return (
    <Card onPress={() => router.push(`/orders/${order.reference}`)} className="gap-2">
      <View className="flex-row items-center justify-between gap-3">
        <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
          {order.provider.display_name}
        </Text>
        <Badge tone={toneFor(order.status)}>{order.status}</Badge>
      </View>

      <View className="flex-row items-center gap-2">
        <Ionicons name="cube-outline" size={14} color={colors.textSubtle} />
        <Text className="text-xs" style={{ color: colors.textMuted }}>
          {order.lines.length} item{order.lines.length === 1 ? '' : 's'} · {order.reference}
        </Text>
      </View>

      <Text className="text-sm font-semibold" style={{ color: colors.text }}>
        {order.total_display}
      </Text>
    </Card>
  );
}
