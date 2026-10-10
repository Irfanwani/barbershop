import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError } from '@/api/client';
import { useMyPayout, useSavePayout } from '@/api/hooks';
import { Button, Card, IconButton, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';

/**
 * The provider's payout account.
 *
 * The account number and IFSC code are write-only: the API masks them on the way
 * back and the app has no code path that could show them in full. Changing them
 * means re-entering both, which is deliberate — a field that cannot be read back
 * cannot leak through a screenshot or a support ticket.
 */
export default function PayoutScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();

  const payout = useMyPayout();
  const save = useSavePayout();

  const [businessName, setBusinessName] = useState('');
  const [beneficiary, setBeneficiary] = useState('');
  const [accountNumber, setAccountNumber] = useState('');
  const [ifsc, setIfsc] = useState('');
  const [error, setError] = useState<string | null>(null);

  const existing = payout.data?.payout_registered ? payout.data : null;

  async function submit() {
    setError(null);
    try {
      await save.mutateAsync({
        business_name: businessName.trim(),
        beneficiary_name: beneficiary.trim(),
        account_number: accountNumber.trim(),
        ifsc_code: ifsc.trim().toUpperCase(),
      });
    } catch (caught) {
      setError(
        isApiError(caught) && caught.fieldErrors.ifsc_code
          ? 'That does not look like a valid IFSC code.'
          : errorMessage(caught, 'Could not save your bank details.'),
      );
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}
      keyboardShouldPersistTaps="handled">
      <IconButton
        name="arrow-back"
        label="Back"
        onPress={() => router.back()}
        className="self-start"
      />

      <View className="gap-2">
        <Text className="text-2xl font-bold tracking-tight" style={{ color: colors.text }}>
          Payout account
        </Text>
        <Text className="text-sm leading-5" style={{ color: colors.textMuted }}>
          Where your earnings are sent. The name has to match your bank account, or
          the payment will bounce.
        </Text>
      </View>

      {existing ? (
        <Card className="gap-1">
          <Text className="text-sm font-semibold" style={{ color: colors.text }}>
            {existing.business_name}
          </Text>
          <Text className="text-xs" style={{ color: colors.textMuted }}>
            {existing.account_number_masked} · {existing.ifsc_code_masked}
          </Text>
          <Text className="text-xs" style={{ color: colors.textSubtle }}>
            Status: {existing.verification_status}
          </Text>
          <Text className="mt-1 text-xs leading-4" style={{ color: colors.textSubtle }}>
            To change these, enter the new details below. Your account goes back for
            verification.
          </Text>
        </Card>
      ) : null}

      <FormError message={error} />

      <Card className="gap-3">
        <Field
          label="Business name"
          placeholder="Sharp Cuts LLP"
          value={businessName}
          onChangeText={setBusinessName}
          testID="payout-business"
        />
        <Field
          label="Beneficiary name"
          placeholder="As it appears on the bank account"
          value={beneficiary}
          onChangeText={setBeneficiary}
          testID="payout-beneficiary"
        />
        <Field
          label="Account number"
          placeholder="00000000000"
          keyboardType="number-pad"
          secureTextEntry
          value={accountNumber}
          onChangeText={setAccountNumber}
          testID="payout-account"
        />
        <Field
          label="IFSC code"
          placeholder="HDFC0001234"
          autoCapitalize="characters"
          value={ifsc}
          onChangeText={(value) => setIfsc(value.toUpperCase())}
          testID="payout-ifsc"
        />

        <Button onPress={submit} loading={save.isPending} testID="payout-save">
          {existing ? 'Update details' : 'Save and verify'}
        </Button>
      </Card>
    </ScrollView>
  );
}