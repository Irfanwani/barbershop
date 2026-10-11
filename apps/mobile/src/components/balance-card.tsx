import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useProviderBalance, useProviderLedger, useWithdraw } from '@/api/hooks';
import { Button, Card, Divider, EmptyState, IconButton, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import { formatPaise } from '@/lib/money';
import type { LedgerEntry } from '@/types/api';

/**
 * What a provider has earned, and taking it.
 *
 * This is the screen the marketplace did not have. Before it, a provider could
 * complete bookings and had nowhere to see the money or ask for it.
 *
 * Two rules are shown rather than hidden: pending earnings cannot be paid out
 * (the appointment has not happened and can still become a no-show), and the
 * whole figure can be traced to a line in the ledger below it.
 */
export function BalanceCard() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const balance = useProviderBalance();
  const ledger = useProviderLedger(1);
  const withdraw = useWithdraw();
  const [error, setError] = useState<string | null>(null);

  async function withdrawAll() {
    setError(null);
    try {
      await withdraw.mutateAsync(undefined);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not request that payout.'));
    }
  }

  const cleared = balance.data?.cleared ?? 0;
  const pending = balance.data?.pending ?? 0;

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

      <View className="gap-1">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Earnings
        </Text>
        <Text className="text-sm" style={{ color: colors.textMuted }}>
          What you have earned from completed appointments, and what you have taken out.
        </Text>
      </View>

      <FormError message={error} />

      <Card className="gap-4">
        <View className="gap-1">
          <Text className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
            Available to withdraw
          </Text>
          <Text className="text-3xl font-bold" style={{ color: colors.text }}>
            {balance.data?.cleared_display ?? '—'}
          </Text>
        </View>

        {pending > 0 ? (
          <View className="flex-row items-start gap-2">
            <Ionicons name="time-outline" size={16} color={colors.textSubtle} />
            <Text className="flex-1 text-xs leading-4" style={{ color: colors.textSubtle }}>
              {pending > 0 ? `${formatPaise(pending)} pending. ` : ''}
              A booking that has not happened yet can still be cancelled or missed, so it
              becomes available once the appointment is finished.
            </Text>
          </View>
        ) : null}

        <Button
          onPress={withdrawAll}
          loading={withdraw.isPending}
          disabled={cleared <= 0}
          testID="withdraw-all">
          {cleared > 0 ? `Withdraw ${balance.data?.cleared_display}` : 'Nothing to withdraw yet'}
        </Button>
      </Card>

      <View className="flex-row gap-3">
        <View className="flex-1">
          <Card className="gap-1">
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              Earned, all time
            </Text>
            <Text className="text-lg font-bold" style={{ color: colors.text }}>
              {balance.data
                ? formatPaise(balance.data.total + balance.data.paid_out)
                : '—'}
            </Text>
          </Card>
        </View>
        <View className="flex-1">
          <Card className="gap-1">
            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              Paid out
            </Text>
            <Text className="text-lg font-bold" style={{ color: colors.text }}>
              {balance.data?.paid_out_display ?? '—'}
            </Text>
          </Card>
        </View>
      </View>

      <View className="gap-2">
        <Text
          className="px-1 text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Statement
        </Text>

        {ledger.isLoading ? (
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Loading your statement…
          </Text>
        ) : (ledger.data?.results.length ?? 0) === 0 ? (
          <EmptyState
            icon="receipt-outline"
            title="Nothing yet"
            body="Every completed appointment appears here with the platform's share shown separately."
          />
        ) : (
          <Card>
            {ledger.data?.results.map((entry, index) => (
              <View key={entry.id}>
                {index > 0 ? <Divider className="my-3" /> : null}
                <LedgerRow entry={entry} />
              </View>
            ))}
          </Card>
        )}
      </View>
    </ScrollView>
  );
}

function LedgerRow({ entry }: { entry: LedgerEntry }) {
  const colors = useColors();
  const credited = entry.amount > 0;

  return (
    <View className="flex-row items-start justify-between gap-3">
      <View className="flex-1">
        <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
          {entry.description || describeLedgerKind(entry.kind)}
        </Text>
        <Text className="text-xs" style={{ color: colors.textSubtle }}>
          {describeLedgerStatus(entry.status)}
          {entry.reference ? ` · ${entry.reference}` : ''}
        </Text>
      </View>
      <Text
        className="text-sm font-semibold"
        style={{ color: credited ? colors.success : colors.textMuted }}>
        {entry.amount_display}
      </Text>
    </View>
  );
}

/** Exported so the wording is tested rather than re-typed per screen. */
export function describeLedgerKind(kind: string): string {
  switch (kind) {
    case 'earning':
      return 'Appointment earned';
    case 'platform_fee':
      return 'BarberShop fee';
    case 'payout':
      return 'Withdrawal';
    case 'refund':
      return 'Refund';
    default:
      return 'Adjustment';
  }
}

export function describeLedgerStatus(status: LedgerEntry['status']): string {
  switch (status) {
    case 'pending':
      return 'Pending';
    case 'cleared':
      return 'Available';
    case 'paid_out':
      return 'Paid out';
    case 'voided':
      return 'Failed';
    default:
      return status;
  }
}
