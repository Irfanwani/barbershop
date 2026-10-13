import { useState } from 'react';
import { Image, ScrollView, Switch, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useMyPayout, useMyServices, useMyShop, useSaveShop } from '@/api/hooks';
import { Button, Card, useColors } from '@/components/ui';
import { FormError } from '@/components/field';
import { SettingsList, type SettingsRow } from '@/components/settings-list';
import { useAuthStore } from '@/store/auth';

export default function ProviderProfile() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const signOut = useAuthStore((state) => state.signOut);

  const shop = useMyShop();
  const services = useMyServices();
  const payout = useMyPayout();
  const saveShop = useSaveShop();

  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const data = shop.data;

  async function toggleAccepting(next: boolean) {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      await saveShop.mutateAsync({ is_accepting_bookings: next });
    } catch (caught) {
      setError(errorMessage(caught, 'Could not update that.'));
    } finally {
      setSaving(false);
    }
  }

  const rows: SettingsRow[] = [
    {
      icon: 'bag-handle-outline',
      title: 'Product orders',
      subtitle: 'Paid, ready and collected',
      onPress: () => router.push('/(provider)/shop-orders'),
    },
    {
      icon: 'card-outline',
      title: 'Payout account',
      subtitle: payout.data?.payout_registered
        ? `Verified · ${payout.data.account_number_masked ?? ''}`
        : 'Add your bank details to get paid',
      onPress: () => router.push('/(provider)/payout'),
    },
    {
      icon: 'barbell-outline',
      title: 'Availability',
      subtitle: 'The hours customers can book in',
      onPress: () => router.push('/(provider)/availability'),
    },
    {
      icon: 'help-circle-outline',
      title: 'Consultation forms',
      subtitle: 'What you need to know before a client sits down',
      onPress: () => router.push('/(provider)/consultation-forms'),
    },
    {
      icon: 'download-outline',
      title: 'Export to a spreadsheet',
      subtitle: 'Bookings, revenue and clients, emailed to you',
      onPress: () => router.push('/(provider)/exports'),
    },
    {
      icon: 'notifications-outline',
      title: 'Notifications',
      subtitle: 'What BarberShop is allowed to tell you',
      onPress: () => router.push('/settings'),
    },
    {
      icon: 'shield-checkmark-outline',
      title: 'Security',
      subtitle: 'Password and recent sign-ins',
      onPress: () => router.push('/settings'),
    },
  ];

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingTop: insets.top + 8,
        paddingBottom: insets.bottom + 32,
        paddingHorizontal: 16,
        gap: 16,
      }}>
      <View className="items-center gap-3 py-4">
        {data?.photo ? (
          <Image
            source={{ uri: data.photo }}
            style={{ width: 88, height: 88, borderRadius: 44 }}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View
            className="h-[88px] w-[88px] items-center justify-center rounded-full"
            style={{ backgroundColor: colors.surface }}>
            <Text className="text-3xl font-bold" style={{ color: colors.textSubtle }}>
              {(data?.display_name ?? '?').slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}
        <View className="items-center gap-1">
          <Text className="text-xl font-bold" style={{ color: colors.text }}>
            {data?.display_name ?? 'Your shop'}
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {data?.address || 'Add an address'}
          </Text>
          <Text className="text-2xs uppercase tracking-wide" style={{ color: colors.textSubtle }}>
            {services.data?.length ?? 0} services ·{' '}
            {Number(data?.rating_average ?? 0).toFixed(1)} ★ ({data?.rating_count ?? 0})
          </Text>
        </View>
      </View>

      {error ? <FormError message={error} /> : null}

      <Card className="gap-1">
        <Text className="text-[15px] font-semibold" style={{ color: colors.text }}>
          Taking bookings
        </Text>
        <Text className="text-xs leading-5" style={{ color: colors.textMuted }}>
          {data?.is_accepting_bookings
            ? 'Customers can book you. Turning this off keeps your shop listed but stops new bookings.'
            : 'New bookings are paused. Existing ones are unaffected.'}
        </Text>
        <View className="flex-row justify-end pt-1">
          <Switch
            value={data?.is_accepting_bookings ?? false}
            onValueChange={(next) => void toggleAccepting(next)}
            disabled={!data || saving}
            trackColor={{ true: colors.accent, false: colors.border }}
            accessibilityLabel="Accepting bookings"
            testID="shop-accepting"
          />
        </View>
      </Card>

      {data?.requires_approval ? (
        <Card>
          <Text className="text-xs leading-5" style={{ color: colors.textMuted }}>
            You review every booking before it is confirmed. Customers see
            “approval needed” on your card.
          </Text>
        </Card>
      ) : null}

      <SettingsList title="Manage" rows={rows} />

      <Button variant="ghost" icon="log-out-outline" onPress={() => void signOut()}>
        Sign out
      </Button>
    </ScrollView>
  );
}