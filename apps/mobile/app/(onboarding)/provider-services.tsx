import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useCreateService } from '@/api/hooks';

/**
 * The first service on a provider's menu.
 *
 * A shop with no services cannot be booked, so this is the last thing standing
 * between a new provider and a finished account. One is enough to finish
 * onboarding; the rest can be added from the services tab.
 *
 * Prices are entered in rupees, because that is how people think about a haircut.
 * The API stores paise.
 */
export default function ProviderServicesScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const createService = useCreateService();

  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [duration, setDuration] = useState('30');
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setError(null);

    const rupees = Number(price.trim());
    if (!name.trim()) return setError('Give the service a name.');
    if (!Number.isFinite(rupees) || rupees <= 0) return setError('Enter a price in rupees.');
    if (rupees > 100_000) return setError('That looks too high. Check the amount.');

    try {
      await createService.mutateAsync({
        name: name.trim(),
        price: Math.round(rupees * 100),
        duration_minutes: Math.max(5, Number(duration.trim()) || 30),
        is_active: true,
      });
      router.replace('/');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not add that service.');
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingTop: insets.top + 24,
        paddingBottom: insets.bottom + 24,
        paddingHorizontal: 24,
        gap: 18,
      }}
      keyboardShouldPersistTaps="handled">
      <View className="gap-2">
        <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
          Add your first service
        </Text>
        <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
          Customers book by service, so a shop needs at least one on the menu.
          You can add the rest whenever.
        </Text>
      </View>

      <FormError message={error} />

      <Field
        label="Service"
        placeholder="Haircut"
        value={name}
        onChangeText={setName}
        testID="service-name"
      />

      <View className="flex-row gap-3">
        <View className="flex-1">
          <Field
            label="Price (₹)"
            placeholder="250"
            keyboardType="numeric"
            value={price}
            onChangeText={setPrice}
            testID="service-price"
          />
        </View>
        <View className="flex-1">
          <Field
            label="Minutes"
            placeholder="30"
            keyboardType="numeric"
            value={duration}
            onChangeText={setDuration}
            testID="service-duration"
          />
        </View>
      </View>

      <Button onPress={submit} loading={createService.isPending} testID="service-save" className="mt-2">
        Finish setup
      </Button>

      <Button
        variant="ghost"
        onPress={() => router.replace('/')}
        testID="service-skip">
        Do this later
      </Button>
    </ScrollView>
  );
}