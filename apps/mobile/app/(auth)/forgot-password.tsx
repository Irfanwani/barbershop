import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { authApi } from '@/api/endpoints';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';

type Stage = 'request' | 'reset';

export default function ForgotPasswordScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const [stage, setStage] = useState<Stage>('request');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function requestCode() {
    setError(null);
    setNotice(null);

    if (!email.trim()) {
      setError('Enter the email you registered with.');
      return;
    }

    setSubmitting(true);
    try {
      const result = await authApi.requestPasswordReset(email.trim());
      // The API always answers the same way, so this is not evidence the account
      // exists. The screen says so rather than implying it does.
      setNotice(result.message);
      setStage('reset');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not send a code. Try again.');
    } finally {
      setSubmitting(false);
    }
  }

  async function resetPassword() {
    setError(null);

    if (password !== confirm) {
      setError('Those passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      await authApi.confirmPasswordReset({
        email: email.trim(),
        code: code.trim(),
        new_password: password,
      });
      setNotice('Password changed. Sign in with the new one.');
      setTimeout(() => router.replace('/(auth)/login'), 1200);
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not reset your password.');
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
        keyboardShouldPersistTaps="handled">
        <View className="gap-2">
          <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
            {stage === 'request' ? 'Reset your password' : 'Enter your code'}
          </Text>
          <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
            {stage === 'request'
              ? 'We will email you a code that works once, for half an hour.'
              : 'Check your inbox, then set the password you want.'}
          </Text>
        </View>

        <FormError message={error} />
        {notice ? (
          <View
            className="rounded-2xl border px-4 py-3"
            style={{ backgroundColor: `${colors.success}14`, borderColor: `${colors.success}40` }}>
            <Text className="text-sm" style={{ color: colors.success }}>
              {notice}
            </Text>
          </View>
        ) : null}

        {stage === 'request' ? (
          <>
            <Field
              label="Email"
              icon="mail-outline"
              placeholder="you@example.com"
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              value={email}
              onChangeText={setEmail}
              onSubmitEditing={requestCode}
              testID="reset-email"
            />
            <Button onPress={requestCode} loading={submitting} testID="reset-request">
              Send me a code
            </Button>
          </>
        ) : (
          <>
            <Field
              label="Code"
              icon="key-outline"
              placeholder="The code from your email"
              autoCapitalize="characters"
              autoCorrect={false}
              value={code}
              onChangeText={(value) => setCode(value.toUpperCase())}
              testID="reset-code"
              className="text-center text-xl tracking-[0.3em]"
            />
            <Field
              label="New password"
              icon="lock-closed-outline"
              placeholder="At least 8 characters"
              secureTextEntry
              autoCapitalize="none"
              value={password}
              onChangeText={setPassword}
              testID="reset-new-password"
            />
            <Field
              label="Confirm new password"
              icon="checkmark-circle-outline"
              placeholder="Type it again"
              secureTextEntry
              autoCapitalize="none"
              value={confirm}
              onChangeText={setConfirm}
              testID="reset-confirm"
            />
            <Button onPress={resetPassword} loading={submitting} testID="reset-submit">
              Set new password
            </Button>
          </>
        )}

        <Text
          className="mt-2 text-center text-sm"
          style={{ color: colors.textMuted }}
          onPress={() => router.back()}>
          Back to sign in
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}