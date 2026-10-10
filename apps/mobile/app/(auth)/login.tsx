import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { authApi } from '@/api/endpoints';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useAuthStore } from '@/store/auth';

export default function LoginScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const setSession = useAuthStore((state) => state.setSession);

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);

    if (!identifier.trim() || !password) {
      setError('Enter your username or email, and your password.');
      return;
    }

    setSubmitting(true);
    try {
      const result = await authApi.login({
        identifier: identifier.trim(),
        password,
      });
      await setSession(result.token, result.user);
      // The root index re-routes from there; doing it here would race it.
      router.replace('/');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not sign in. Try again.');
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
          paddingTop: insets.top + 32,
          paddingBottom: insets.bottom + 32,
          paddingHorizontal: 24,
          gap: 20,
        }}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag">
        <View className="gap-2">
          <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
            Welcome back
          </Text>
          <Text className="text-base" style={{ color: colors.textMuted }}>
            Sign in to pick up where you left off.
          </Text>
        </View>

        <FormError message={error} />

        <Field
          label="Username or email"
          icon="person-outline"
          placeholder="you@example.com"
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete="username"
          textContentType="username"
          value={identifier}
          onChangeText={setIdentifier}
          testID="login-identifier"
        />

        <Field
          label="Password"
          icon="lock-closed-outline"
          placeholder="Your password"
          secureTextEntry
          autoCapitalize="none"
          autoComplete="current-password"
          textContentType="password"
          value={password}
          onChangeText={setPassword}
          onSubmitEditing={submit}
          returnKeyType="go"
          testID="login-password"
        />

        <Button
          onPress={submit}
          loading={submitting}
          testID="login-submit"
          className="mt-2">
          Sign in
        </Button>

        <View className="mt-2 flex-row items-center justify-between">
          <Text
            className="text-sm"
            style={{ color: colors.textMuted }}
            onPress={() => router.push('/(auth)/forgot-password')}>
            Forgot your password?
          </Text>
          <Text
            className="text-sm font-semibold"
            style={{ color: colors.accent }}
            onPress={() => router.push('/(auth)/register')}>
            Create an account
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}