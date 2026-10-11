import { useState } from 'react';
import { Image, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, Card, useColors } from '@/components/ui';
import { Field } from '@/components/field';
import { useAuthStore, useRole } from '@/store/auth';
import { SettingsList, type SettingsRow } from '@/components/settings-list';
import { useDeleteAccount, useUpdateMe } from '@/api/hooks';

export default function ProfileScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const user = useAuthStore((state) => state.user);
  const signOut = useAuthStore((state) => state.signOut);
  const role = useRole();

  const [editing, setEditing] = useState(false);
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [lastName, setLastName] = useState(user?.last_name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');

  const update = useUpdateMe();
  const remove = useDeleteAccount();

  const rows: SettingsRow[] = [
    {
      icon: 'pricetag-outline',
      title: 'Prices',
      subtitle: 'What shops here usually charge',
      onPress: () => router.push('/prices'),
    },
    {
      icon: 'bag-handle-outline',
      title: 'My orders',
      subtitle: 'Products you have bought and their status',
      onPress: () => router.push('/orders'),
    },
    {
      icon: 'location-outline',
      title: 'Saved location',
      subtitle: 'Where the browse list searches from',
      onPress: () => router.push('/(onboarding)/customer-location'),
    },
    {
      icon: 'shield-checkmark-outline',
      title: 'Security',
      subtitle: 'Change your password, see recent sign-ins',
      onPress: () => router.push('/settings'),
    },
    {
      icon: 'notifications-outline',
      title: 'Notifications',
      subtitle: 'What BarberShop is allowed to tell you',
      onPress: () => router.push('/settings'),
    },
  ];

  async function save() {
    await update.mutateAsync({ first_name: firstName, last_name: lastName, phone });
    setEditing(false);
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingTop: insets.top + 8,
        paddingBottom: insets.bottom + 24,
        paddingHorizontal: 16,
        gap: 16,
      }}>
      <View className="items-center gap-3 py-4">
        {user?.avatar ? (
          <Image
            source={{ uri: user.avatar }}
            style={{ width: 88, height: 88, borderRadius: 44 }}
            accessibilityIgnoresInvertColors
          />
        ) : (
          <View
            className="h-[88px] w-[88px] items-center justify-center rounded-full"
            style={{ backgroundColor: colors.surface }}>
            <Text className="text-3xl font-bold" style={{ color: colors.textSubtle }}>
              {(user?.display_name ?? '?').slice(0, 1).toUpperCase()}
            </Text>
          </View>
        )}

        <View className="items-center gap-1">
          <Text className="text-xl font-bold" style={{ color: colors.text }}>
            {user?.display_name}
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            {user?.email}
          </Text>
          <Text className="text-2xs uppercase tracking-wide" style={{ color: colors.textSubtle }}>
            {role === 'provider' ? 'Service provider' : 'Customer'}
          </Text>
        </View>
      </View>

      {editing ? (
        <Card className="gap-3">
          <Field label="First name" value={firstName} onChangeText={setFirstName} />
          <Field label="Last name" value={lastName} onChangeText={setLastName} />
          <Field
            label="Phone"
            keyboardType="phone-pad"
            value={phone}
            onChangeText={setPhone}
          />
          <View className="flex-row gap-2">
            <Button variant="secondary" onPress={() => setEditing(false)} className="flex-1">
              Cancel
            </Button>
            <Button onPress={save} loading={update.isPending} className="flex-1">
              Save
            </Button>
          </View>
        </Card>
      ) : (
        <Button variant="secondary" icon="create-outline" onPress={() => setEditing(true)}>
          Edit profile
        </Button>
      )}

      <SettingsList rows={rows} />

      <Button variant="ghost" icon="log-out-outline" onPress={() => void signOut()}>
        Sign out
      </Button>

      <Button
        variant="ghost"
        onPress={() => {
          if (remove.isPending) return;
          void remove.mutateAsync();
          void signOut();
        }}>
        {remove.isPending ? 'Deleting…' : 'Delete my account'}
      </Button>
    </ScrollView>
  );
}