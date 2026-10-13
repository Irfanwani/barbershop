import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useClearRiskFlag, useCustomerRisk } from '@/api/hooks';
import { Button, Card, Divider, useColors } from '@/components/ui';

/**
 * What a customer has done before, and what the platform suggests.
 *
 * Deliberately advisory. Nothing on this screen changes what the customer is
 * charged or whether they can book - it is information for the provider to
 * weigh when they set their own deposit policy. A screen that looked like a
 * verdict would be one providers either obeyed blindly or stopped opening.
 */
export function CustomerRiskSheet({
  customerId,
  displayName,
  onClose,
}: {
  customerId: number;
  displayName: string;
  onClose: () => void;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const risk = useCustomerRisk(customerId);
  const clearFlag = useClearRiskFlag();

  const data = risk.data;
  const tone =
    data?.risk_level === 'high'
      ? colors.danger
      : data?.risk_level === 'medium'
        ? colors.warning
        : colors.success;

  return (
    <View className="absolute inset-0 justify-end" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      <View
        className="max-h-[80%] rounded-t-3xl"
        style={{ backgroundColor: colors.background, paddingBottom: insets.bottom + 16 }}>
        <View
          className="flex-row items-center justify-between px-5 py-4"
          style={{ borderBottomColor: colors.border, borderBottomWidth: 1 }}>
          <Text className="text-lg font-semibold" style={{ color: colors.text }}>
            {displayName}
          </Text>
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
            <Ionicons name="close" size={22} color={colors.textMuted} />
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }}>
          {risk.isError ? (
            <Text className="text-sm" style={{ color: colors.danger }}>
              {errorMessage(risk.error, 'Could not load their record.')}
            </Text>
          ) : !data ? (
            <Text className="text-sm" style={{ color: colors.textMuted }}>
              Loading…
            </Text>
          ) : (
            <>
              <Card className="gap-2">
                <View className="flex-row items-center justify-between">
                  <Text className="text-2xs font-semibold uppercase tracking-wide" style={{ color: colors.textSubtle }}>
                    Record at your shop
                  </Text>
                  {data.risk_level ? (
                    <Text
                      className="text-xs font-semibold"
                      style={{ color: tone }}
                      testID="risk-level">
                      {data.risk_level}
                    </Text>
                  ) : null}
                </View>
                <Text className="text-sm" style={{ color: colors.textMuted }}>
                  {data.total_bookings === 0
                    ? 'No appointments here yet.'
                    : `${data.completed} of ${data.total_bookings} appointments completed${
                        data.no_shows > 0 ? `, ${data.no_shows} not turned up to` : ''
                      }.`}
                </Text>
                {data.total_bookings > 0 ? (
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    {Math.round(data.no_show_rate * 100)}% no-show ·{' '}
                    {Math.round(data.cancel_rate * 100)}% cancelled
                  </Text>
                ) : null}
              </Card>

              {data.risk_level ? (
                <Card className="gap-2">
                  <View className="flex-row items-center justify-between">
                    <Text className="text-sm font-semibold" style={{ color: colors.text }}>
                      Suggested deposit
                    </Text>
                    <Text className="text-sm font-semibold" style={{ color: tone }}>
                      {data.suggested_deposit_percent}%
                    </Text>
                  </View>
                  <Text className="text-xs" style={{ color: colors.textMuted }}>
                    A suggestion, not a price. It does not change what the customer
                    pays unless you raise the deposit on the service yourself.
                  </Text>
                </Card>
              ) : (
                <Text className="text-xs leading-4" style={{ color: colors.textSubtle }}>
                  {data.total_bookings === 0
                    ? 'No history here to judge. New customers are not treated as risky — otherwise every first booking would need a deposit.'
                    : 'Nothing here stands out. A long clean record is not riskier than a short one, and not safer either — it just means nothing to change.'}
                </Text>
              )}

              {data.flags.map((flag) => (
                <Card key={flag.id} className="gap-2">
                  <View className="flex-row items-center justify-between">
                    <Text className="text-sm font-medium" style={{ color: colors.text }}>
                      {flag.reason}
                    </Text>
                    <Text className="text-2xs" style={{ color: colors.textSubtle }}>
                      {flag.severity}
                    </Text>
                  </View>
                  <Divider className="my-1" />
                  <Button
                    variant="ghost"
                    onPress={() => void clearFlag.mutateAsync(flag.id)}
                    testID={`clear-flag-${flag.id}`}>
                    Clear this
                  </Button>
                  <Text className="text-2xs" style={{ color: colors.textSubtle }}>
                    Forgiving it keeps the record of what happened, and lets them
                    move past a bad month.
                  </Text>
                </Card>
              ))}
            </>
          )}
        </ScrollView>
      </View>
    </View>
  );
}
