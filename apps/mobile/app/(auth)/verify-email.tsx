import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { authApi } from '@/api/endpoints';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useAuthStore } from '@/store/auth';

export default function VerifyEmailScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const setUser = useAuthStore((state) => state.setUser);
  const signOut = useAuthStore((state) => state.signOut);

  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);

  // Offer a fresh code immediately; people usually arrive here because the one
  // we emailed has expired or landed in spam.
  useEffect(() => {
    let cancelled = false;
    void authApi
      .resendVerification()
      .then((result) => {
        if (!cancelled) {
          setNotice(result.message);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled && isApiError(caught)) setError(caught.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit() {
    setError(null);
    setNotice(null);

    if (code.trim().length < 4) {
      setError('Enter the code from your email.');
      return;
    }

    setSubmitting(true);
    try {
      const result = await authApi.verifyEmail(code.trim());
      setUser(result.user);
      router.replace('/');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'That did not work. Try again.');
    } finally {
      setSubmitting(false);
    }
  }

  async function resend() {
    setResending(true);
    setError(null);
    try {
      const result = await authApi.resendVerification();
      setNotice(result.message);
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not send another code.');
    } finally {
      setResending(false);
    }
  }

  return (
    <KeyboardAvoidingView
      className="flex-1"
      style={{ backgroundColor: colors.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={{
          paddingTop: insets.top + 40,
          paddingBottom: insets.bottom + 32,
          paddingHorizontal: 24,
          gap: 20,
        }}
        keyboardShouldPersistTaps="handled">
        <View className="gap-2">
          <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
            Confirm your email
          </Text>
          <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
            We sent a code to your inbox. It works once and expires in 24 hours.
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

        <Field
          label="Verification code"
          placeholder="ABCD2345"
          autoCapitalize="characters"
          autoCorrect={false}
          value={code}
          onChangeText={(value) => setCode(value.toUpperCase())}
          onSubmitEditing={submit}
          returnKeyType="go"
          testID="verify-code"
          className="text-center text-2xl tracking-[0.3em]"
        />

        <Button onPress={submit} loading={submitting} testID="verify-submit">
          Confirm
        </Button>

        <Button variant="ghost" onPress={resend} loading={resending}>
          Send another code
        </Button>

        <Text
          className="mt-2 text-center text-sm"
          style={{ color: colors.textMuted }}
          onPress={() => void signOut()}>
          Use a different account
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}