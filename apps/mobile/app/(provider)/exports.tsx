/**
 * Asking for a spreadsheet.
 *
 * The screen exists mostly to explain the wait. A year of bookings is built by
 * a worker and arrives by email, and a button that returns nothing for two
 * minutes is a button people press four times.
 */
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useExports, useRequestExport } from '@/api/hooks';
import { Button, Card, Divider, EmptyState, useColors } from '@/components/ui';
import { FormError } from '@/components/field';

const PERIODS = [
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'Last 12 months', days: 365 },
] as const;

const DATASETS = [
  { value: 'bookings', label: 'Bookings', blurb: 'Every appointment in the period' },
  { value: 'revenue', label: 'Revenue', blurb: 'What was earned and paid out' },
  { value: 'clients', label: 'Clients', blurb: 'One row per customer, with counts' },
  { value: 'payouts', label: 'Payouts', blurb: 'Everything that left your balance' },
] as const;

function isoDaysAgo(days: number): string {
  const when = new Date();
  when.setDate(when.getDate() - days);
  return when.toISOString().slice(0, 10);
}

export default function ProviderExports() {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  const exports = useExports();
  const request = useRequestExport();

  const [days, setDays] = useState(90);
  const [datasets, setDatasets] = useState<string[]>(['bookings', 'revenue']);
  const [error, setError] = useState<string | null>(null);

  function toggle(value: string) {
    setDatasets((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  }

  async function submit() {
    setError(null);
    if (datasets.length === 0) {
      setError('Pick at least one thing to export.');
      return;
    }
    try {
      await request.mutateAsync({
        from_date: isoDaysAgo(days),
        to_date: new Date().toISOString().slice(0, 10),
        datasets,
      });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not start that export.'));
    }
  }

  const rows = exports.data ?? [];

  return (
    <SafeAreaView className="flex-1" style={{ backgroundColor: colors.background }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: insets.bottom + 32 }}>
        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            Export
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            We email you the files rather than letting you download them. A copy of
            your data sitting on a server is a copy somebody eventually shares.
          </Text>
        </View>

        <Card className="gap-3">
          <Text className="text-sm font-medium" style={{ color: colors.text }}>
            Period
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {PERIODS.map((period) => (
              <Button
                key={period.days}
                variant={days === period.days ? 'primary' : 'secondary'}
                onPress={() => setDays(period.days)}
                testID={`period-${period.days}`}>
                {period.label}
              </Button>
            ))}
          </View>

          <Divider />

          <Text className="text-sm font-medium" style={{ color: colors.text }}>
            What to include
          </Text>
          {DATASETS.map((dataset) => {
            const on = datasets.includes(dataset.value);
            return (
              <Button
                key={dataset.value}
                variant={on ? 'primary' : 'ghost'}
                onPress={() => toggle(dataset.value)}
                testID={`dataset-${dataset.value}`}>
                {dataset.label}
              </Button>
            );
          })}
          <Text className="text-xs leading-4" style={{ color: colors.textSubtle }}>
            Amounts come out in two columns: the plain number in paise, and a
            formatted one for reading. Dates come out in UTC and in your shop’s own
            time zone, because those are not always the same.
          </Text>

          <FormError message={error} />

          <Button onPress={() => void submit()} loading={request.isPending} testID="request-export">
            Email me this
          </Button>
          <Text className="text-2xs" style={{ color: colors.textSubtle }}>
            Every appointment in the period comes out, not just the ones on the
            first page. It can take a minute for a long year.
          </Text>
        </Card>

        {rows.map((row) => (
          <Card key={row.id} className="gap-1">
            <View className="flex-row items-center justify-between">
              <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                {row.from_date} to {row.to_date}
              </Text>
              <Text
                className="text-xs font-semibold"
                style={{
                  color:
                    row.status === 'sent'
                      ? colors.success
                      : row.status === 'failed'
                        ? colors.danger
                        : colors.textMuted,
                }}
                testID={`export-status-${row.id}`}>
                {row.status === 'sent' ? 'Sent' : row.status === 'failed' ? 'Failed' : 'On its way'}
              </Text>
            </View>
            <Text className="text-xs" style={{ color: colors.textMuted }}>
              {row.row_count > 0 ? `${row.row_count} rows · ` : ''}
              {row.datasets.join(', ')}
            </Text>
            {row.failure_reason ? (
              <Text className="text-xs" style={{ color: colors.danger }}>
                {row.failure_reason}
              </Text>
            ) : null}
          </Card>
        ))}

        {!exports.isLoading && rows.length === 0 ? (
          <EmptyState
            icon="download-outline"
            title="Nothing exported yet"
            body="Every salon runs on a spreadsheet. If your data cannot leave BarberShop, you will keep two sets of numbers, and ours will be the stale one."
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
