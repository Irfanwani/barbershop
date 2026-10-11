import { ScrollView, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useOrder, useOrderAction } from '@/api/hooks';
import { Badge, Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import { useState } from 'react';
import type { OrderStatus } from '@/types/api';

const STATUS_COPY: Record<OrderStatus, { label: string; body: string }> = {
  pending: {
    label: 'Awaiting payment',
    body: 'We have your order. Pay at the shop when you collect.',
  },
  paid: { label: 'Paid', body: 'Paid. The shop is getting it ready.' },
  ready: { label: 'Ready', body: 'Ready to collect from the shop.' },
  collected: { label: 'Collected', body: 'Collected. Thanks for coming in.' },
  cancelled: { label: 'Cancelled', body: 'This order was cancelled and the items returned to stock.' },
  refunded: { label: 'Refunded', body: 'This order was refunded.' },
};

export default function OrderDetailScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { reference } = useLocalSearchParams<{ reference: string }>();
  const act = useOrderAction();
  const [error, setError] = useState<string | null>(null);

  const order = useOrder(reference ?? null);
  const copy = order.data ? STATUS_COPY[order.data.status] : null;

  async function move(action: 'cancel' | 'ready' | 'collect') {
    setError(null);
    try {
      await act.mutateAsync({ reference: order.data!.reference, action });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not do that.'));
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
      <IconButton name="arrow-back" label="Back" onPress={() => router.back()} className="self-start" />

      {order.isLoading ? (
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          Loading your order…
        </Text>
      ) : !order.data ? (
        <EmptyState
          icon="cube-outline"
          title="Order not found"
          body="Check the reference and try again."
        />
      ) : (
        <>
          <View className="gap-2">
            <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
              {order.data.reference}
            </Text>
            <Badge tone={order.data.status === 'cancelled' ? 'danger' : 'success'}>
              {copy?.label ?? order.data.status}
            </Badge>
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              {copy?.body}
            </Text>
          </View>

          <FormError message={error} />

          <Card className="gap-2">
            <Text className="text-sm font-semibold" style={{ color: colors.text }}>
              {order.data.provider.display_name}
            </Text>
            {order.data.provider.address ? (
              <Text className="text-xs" style={{ color: colors.textSubtle }}>
                {order.data.provider.address}
              </Text>
            ) : null}
          </Card>

          <Card>
            {order.data.lines.map((line, index) => (
              <View key={line.product}>
                {index > 0 ? <Divider className="my-3" /> : null}
                <View className="flex-row items-center justify-between gap-3">
                  <View className="flex-1">
                    <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                      {line.name}
                    </Text>
                    <Text className="text-xs" style={{ color: colors.textSubtle }}>
                      {line.quantity} × {formatPaise(line.unit_price)}
                    </Text>
                  </View>
                  <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                    {formatPaise(line.line_total)}
                  </Text>
                </View>
              </View>
            ))}
          </Card>

          <Card className="gap-1">
            <Row label="Subtotal" value={formatPaise(order.data.subtotal)} />
            <Row label="Service fee" value={formatPaise(order.data.platform_fee)} />
            <Divider className="my-2" />
            <Row label="Total" value={order.data.total_display} emphasis />
          </Card>

          {order.data.can_be_paid ? (
            <Button onPress={() => move('cancel')} variant="ghost" loading={act.isPending}>
              Cancel order
            </Button>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}

function Row({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  const colors = useColors();
  return (
    <View className="flex-row items-center justify-between">
      <Text
        className={emphasis ? 'text-base font-bold' : 'text-sm'}
        style={{ color: emphasis ? colors.text : colors.textMuted }}>
        {label}
      </Text>
      <Text
        className={emphasis ? 'text-base font-bold' : 'text-sm'}
        style={{ color: emphasis ? colors.text : colors.textMuted }}>
        {value}
      </Text>
    </View>
  );
}

function formatPaise(minor: number): string {
  return `₹${(minor / 100).toFixed(2)}`;
}
