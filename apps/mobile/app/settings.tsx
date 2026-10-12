import { useEffect, useState } from 'react';
import { ScrollView, Switch, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { errorMessage, isApiError } from '@/api/client';
import { meApi } from '@/api/endpoints';
import { Button, Card, Divider, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useAuthStore } from '@/store/auth';
import {
  NOTIFICATION_CATALOGUE,
  useNotificationPreferencesStore,
} from '@/store/notification-preferences';
import { useNotificationPreferences } from '@/api/hooks';

/**
 * Security and notifications.
 *
 * Both were unreachable from the app before. The store was split across two
 * apps and neither exposed a preference screen, so every user received every
 * push forever with no way to stop any of it.
 */
export default function SettingsScreen() {
  const colors = useColors();
  const router = useRouter();
  const email = useAuthStore((state) => state.user?.email);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  async function changePassword() {
    setError(null);
    setSaved(false);
    setSaving(true);
    try {
      await meApi.changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setSaved(true);
    } catch (caught) {
      setError(
        isApiError(caught) && caught.fieldErrors.current_password
          ? 'That is not your current password.'
          : errorMessage(caught, 'Could not change your password.'),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, gap: 20, paddingBottom: 48 }}>
      <IconButton
        name="arrow-back"
        label="Back"
        onPress={() => router.back()}
        className="self-start"
      />

      <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
        Settings
      </Text>

      <NotificationSettings />

      <View className="gap-2">
        <Text
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Change password
        </Text>
        <Card className="gap-3">
          <FormError message={error} />
          <Field
            label="Current password"
            secureTextEntry
            autoCapitalize="none"
            value={currentPassword}
            onChangeText={setCurrentPassword}
            testID="settings-current-password"
          />
          <Field
            label="New password"
            secureTextEntry
            autoCapitalize="none"
            value={newPassword}
            onChangeText={setNewPassword}
            testID="settings-new-password"
          />
          <Button onPress={changePassword} loading={saving} testID="settings-change-password">
            Update password
          </Button>
          {saved ? (
            <Text className="text-sm" style={{ color: colors.success }}>
              Password updated. Every other device has been signed out.
            </Text>
          ) : null}
        </Card>
      </View>

      <View className="gap-2">
        <Text
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: colors.textSubtle }}>
          Account
        </Text>
        <Card className="gap-1">
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            Signed in as {email}
          </Text>
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            Tokens live in your device keychain and never in plain storage.
          </Text>
        </Card>
      </View>
    </ScrollView>
  );
}

function NotificationSettings() {
  const colors = useColors();
  const preferences = useNotificationPreferencesStore((state) => state.preferences);
  const setPreference = useNotificationPreferencesStore((state) => state.set);
  const synced = useNotificationPreferencesStore((state) => state.synced);

  // Pull the server's answer whenever this screen is opened, so a change made
  // on another phone is reflected before anybody touches a switch.
  const { data } = useNotificationPreferences();
  const acceptFromServer = useNotificationPreferencesStore((state) => state.acceptFromServer);

  useEffect(() => {
    if (data?.preferences) {
      acceptFromServer(data.preferences as Partial<typeof preferences>);
    }
  }, [data, acceptFromServer]);

  return (
    <View className="gap-2">
      {!synced ? (
        <Text className="text-xs" style={{ color: colors.textSubtle }}>
          Syncing with your account…
        </Text>
      ) : null}

      <Text
        className="text-xs font-semibold uppercase tracking-wide"
        style={{ color: colors.textSubtle }}>
        Notifications
      </Text>

      <Card>
        {NOTIFICATION_CATALOGUE.map((entry, index) => {
          const enabled = preferences[entry.key] ?? entry.defaultEnabled;
          return (
            <View key={entry.key}>
              {index > 0 ? <Divider className="my-3" /> : null}
              <View className="flex-row items-center justify-between gap-3">
                <View className="flex-1">
                  <Text className="text-[15px] font-medium" style={{ color: colors.text }}>
                    {entry.label}
                  </Text>
                  <Text className="text-xs" style={{ color: colors.textSubtle }}>
                    {entry.description}
                  </Text>
                </View>
                <Switch
                  value={enabled}
                  onValueChange={(next) => setPreference(entry.key, next)}
                  disabled={entry.required}
                  trackColor={{ true: colors.accent, false: colors.border }}
                  accessibilityLabel={entry.label}
                  testID={`notify-${entry.key}`}
                />
              </View>
            </View>
          );
        })}
      </Card>
    </View>
  );
}