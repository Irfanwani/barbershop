/**
 * Managing API keys.
 *
 * The screen has one job that matters: the secret is shown exactly once, and
 * the screen says so at the moment it is shown, because there is no way back.
 * Everything else here is bookkeeping.
 */

import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage } from '@/api/client';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/api/hooks';
import { Button, Card, Divider, EmptyState, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';

const SCOPES = [
  { value: 'read', label: 'Read', blurb: 'See this account\'s bookings' },
  { value: 'write', label: 'Write', blurb: 'Book, change and cancel' },
] as const;

export default function ApiKeysScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  const keys = useApiKeys();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['read']);
  const [issued, setIssued] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggleScope(scope: string) {
    setScopes((current) =>
      current.includes(scope)
        ? current.filter((value) => value !== scope)
        : [...current, scope],
    );
  }

  async function submit() {
    setError(null);
    if (!name.trim()) {
      setError('Give the key a name you will recognise in six months.');
      return;
    }
    if (scopes.length === 0) {
      setError('A key that can do nothing is not worth having.');
      return;
    }
    try {
      const created = await create.mutateAsync({ name: name.trim(), scopes });
      setIssued(created.key);
      setOpen(false);
      setName('');
      setScopes(['read']);
    } catch (caught) {
      setError(errorMessage(caught, 'Could not create that key.'));
    }
  }

  return (
    <SafeAreaView className="flex-1" style={{ backgroundColor: colors.background }} edges={['top']}>
      <ScrollView
        contentContainerStyle={{ padding: 16, gap: 16, paddingBottom: insets.bottom + 32 }}>
        <View className="gap-1">
          <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
            API keys
          </Text>
          <Text className="text-sm" style={{ color: colors.textMuted }}>
            For a till, a dashboard, or anything else that needs to talk to
            BarberShop without logging in as you.
          </Text>
        </View>

        {issued ? (
          <Card className="gap-2">
            <View className="flex-row items-center justify-between">
              <Text className="text-base font-semibold" style={{ color: colors.text }}>
                Copy this now
              </Text>
              <Ionicons name="warning-outline" size={20} color={colors.warning} />
            </View>
            <Text className="text-xs" style={{ color: colors.textMuted }}>
              We only show it this once. There is nothing stored that could show
              it to you again - delete this and make another if you lose it.
            </Text>
            <Text
              className="rounded-xl p-3 text-xs"
              style={{ backgroundColor: colors.surfaceRaised, color: colors.text }}
              testID="issued-key">
              {issued}
            </Text>
            <Button variant="ghost" onPress={() => setIssued(null)} testID="dismiss-key">
              I have copied it
            </Button>
          </Card>
        ) : null}

        {open ? (
          <Card className="gap-3">
            <Field
              label="Name"
              placeholder="Front till"
              value={name}
              onChangeText={setName}
              testID="key-name"
            />

            <View className="gap-2">
              <Text className="text-sm font-medium" style={{ color: colors.text }}>
                What it can do
              </Text>
              {SCOPES.map((scope) => {
                const on = scopes.includes(scope.value);
                return (
                  <Pressable
                    key={scope.value}
                    onPress={() => toggleScope(scope.value)}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: on }}
                    testID={`scope-${scope.value}`}
                    className="flex-row items-center gap-3 rounded-2xl border px-4 py-3"
                    style={{
                      backgroundColor: on ? `${colors.accent}12` : colors.surface,
                      borderColor: on ? colors.accent : colors.border,
                    }}>
                    <Ionicons
                      name={on ? 'checkbox' : 'square-outline'}
                      size={20}
                      color={on ? colors.accent : colors.textSubtle}
                    />
                    <View className="flex-1">
                      <Text className="text-sm font-medium" style={{ color: colors.text }}>
                        {scope.label}
                      </Text>
                      <Text className="text-xs" style={{ color: colors.textSubtle }}>
                        {scope.blurb}
                      </Text>
                    </View>
                  </Pressable>
                );
              })}
              <Text className="text-xs leading-4" style={{ color: colors.textSubtle }}>
                A key acts as your account, and only yours. Read cannot write,
                and you can narrow or revoke a key at any time.
              </Text>
            </View>

            <FormError message={error} />

            <Button onPress={() => void submit()} loading={create.isPending} testID="create-key">
              Create key
            </Button>
          </Card>
        ) : (
          <Button onPress={() => setOpen(true)} testID="new-key">
            Create an API key
          </Button>
        )}

        {(keys.data ?? []).map((item) => (
          <Card key={item.id} className="gap-2">
            <View className="flex-row items-center justify-between">
              <Text className="text-base font-semibold" style={{ color: colors.text }}>
                {item.name}
              </Text>
              {!item.is_active || item.is_expired ? (
                <Text className="text-xs" style={{ color: colors.danger }}>
                  {item.is_expired ? 'expired' : 'revoked'}
                </Text>
              ) : null}
            </View>

            <Text className="text-xs" style={{ color: colors.textSubtle }}>
              {item.prefix}… · {item.scopes.join(', ') || 'no permissions'}
            </Text>

            <Text className="text-xs" style={{ color: colors.textMuted }}>
              {item.last_used_at
                ? `Last used ${new Date(item.last_used_at).toLocaleDateString()}`
                : 'Never used'}
            </Text>

            {item.is_active && !item.is_expired ? (
              <>
                <Divider className="my-1" />
                <Button
                  variant="ghost"
                  onPress={() => void revoke.mutateAsync(item.id)}
                  loading={revoke.isPending && revoke.variables === item.id}
                  testID={`revoke-${item.id}`}>
                  Revoke now
                </Button>
                <Text className="text-2xs" style={{ color: colors.textSubtle }}>
                  Stops working immediately. The record stays so you can see what it
                  was doing.
                </Text>
              </>
            ) : null}
          </Card>
        ))}

        {!keys.isLoading && (keys.data ?? []).length === 0 && !open ? (
          <EmptyState
            icon="key-outline"
            title="No keys yet"
            body="A key lets a till or a dashboard read and write your bookings without anybody logging in as you. You can revoke one the moment it stops being trusted."
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
