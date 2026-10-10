import { useState } from 'react';
import { Ionicons } from '@expo/vector-icons';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { authApi } from '@/api/endpoints';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { cn } from '@/lib/cn';
import { useAuthStore } from '@/store/auth';

type Choice = {
  role: 'customer' | 'provider';
  title: string;
  body: string;
  icon: 'person-outline' | 'cut-outline';
};

const CHOICES: Choice[] = [
  {
    role: 'customer',
    title: 'I need a haircut',
    body: 'Find shops near you, book a slot, pay and review.',
    icon: 'person-outline',
  },
  {
    role: 'provider',
    title: 'I run a shop',
    body: 'Take bookings, manage your menu and get paid.',
    icon: 'cut-outline',
  },
];

export default function RegisterScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const setSession = useAuthStore((state) => state.setSession);

  const [role, setRole] = useState<'customer' | 'provider'>('customer');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');

  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);
    setFieldErrors({});

    if (password !== confirm) {
      setFieldErrors({ confirm: 'These do not match.' });
      return;
    }

    setSubmitting(true);
    try {
      const result = await authApi.register({
        username: username.trim(),
        email: email.trim(),
        password,
        role,
      });
      await setSession(result.token, result.user);
      router.replace('/');
    } catch (caught) {
      if (isApiError(caught)) {
        setError(caught.message);
        const errors = caught.fieldErrors;
        // Only set the ones the server actually complained about, so a field the
        // user already fixed is not re-marked from a stale response.
        const next: Record<string, string> = {};
        if (errors.username?.[0]) next.username = errors.username[0];
        if (errors.email?.[0]) next.email = errors.email[0];
        if (errors.password?.[0]) next.password = errors.password[0];
        setFieldErrors(next);
      } else {
        setError('Could not create your account. Try again.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <KeyboardAvoidingView
      className="flex-1"
      style={{ backgroundColor: colors.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 24,
          paddingBottom: insets.bottom + 32,
          paddingHorizontal: 24,
          gap: 18,
        }}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag">
        <View className="gap-2">
          <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
            Create your account
          </Text>
          <Text className="text-base" style={{ color: colors.textMuted }}>
            One app, two sides. Pick the one that is you — you can run a shop and
            still book as a customer elsewhere.
          </Text>
        </View>

        <View className="gap-3">
          {CHOICES.map((choice) => {
            const selected = role === choice.role;
            return (
              <Pressable
                key={choice.role}
                onPress={() => setRole(choice.role)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                testID={`role-${choice.role}`}
                className={cn(
                  'flex-row items-start gap-3 rounded-2xl border p-4',
                  selected && 'border-2',
                )}
                style={{
                  backgroundColor: selected ? `${colors.accent}12` : colors.surface,
                  borderColor: selected ? colors.accent : colors.border,
                }}>
                <View
                  className="h-10 w-10 items-center justify-center rounded-xl"
                  style={{ backgroundColor: selected ? colors.accent : colors.surfaceRaised }}>
                  <Ionicons
                    name={choice.icon}
                    size={20}
                    color={selected ? colors.accentText : colors.textMuted}
                  />
                </View>
                <View className="flex-1 gap-0.5">
                  <Text className="text-base font-semibold" style={{ color: colors.text }}>
                    {choice.title}
                  </Text>
                  <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
                    {choice.body}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </View>

        <FormError message={error} />

        <Field
          label="Username"
          icon="at-outline"
          placeholder="How your name appears"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="username"
          value={username}
          onChangeText={setUsername}
          error={fieldErrors.username ?? null}
          testID="register-username"
        />

        <Field
          label="Email"
          icon="mail-outline"
          placeholder="you@example.com"
          keyboardType="email-address"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="email"
          textContentType="emailAddress"
          value={email}
          onChangeText={setEmail}
          error={fieldErrors.email ?? null}
          testID="register-email"
        />

        <Field
          label="Password"
          icon="lock-closed-outline"
          placeholder="At least 8 characters"
          secureTextEntry
          autoCapitalize="none"
          autoComplete="new-password"
          value={password}
          onChangeText={setPassword}
          error={fieldErrors.password ?? null}
          hint="Use something a person would not guess."
          testID="register-password"
        />

        <Field
          label="Confirm password"
          icon="checkmark-circle-outline"
          placeholder="Type it again"
          secureTextEntry
          autoCapitalize="none"
          value={confirm}
          onChangeText={setConfirm}
          error={fieldErrors.confirm ?? null}
          testID="register-confirm"
        />

        <Button onPress={submit} loading={submitting} testID="register-submit" className="mt-2">
          Create account
        </Button>

        <Text
          className="mt-1 text-center text-sm"
          style={{ color: colors.textMuted }}
          onPress={() => router.push('/(auth)/login')}>
          Already have one? <Text style={{ color: colors.accent }}>Sign in</Text>
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
