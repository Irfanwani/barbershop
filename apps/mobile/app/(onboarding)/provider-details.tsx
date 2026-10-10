import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import * as Location from 'expo-location';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useCreateShop , useServiceTypes } from '@/api/hooks';
import type { ServiceType } from '@/types/api';

const FALLBACK_TYPES: { value: ServiceType; label: string }[] = [
  { value: 'barbershop', label: 'Barber shop' },
  { value: 'hair_salon', label: 'Hair salon' },
  { value: 'beauty_salon', label: 'Beauty salon' },
  { value: 'full_service_salon', label: 'Full service salon' },
  { value: 'spa', label: 'Spa' },
  { value: 'massage', label: 'Massage' },
  { value: 'other', label: 'Other' },
];

/**
 * A provider's shop.
 *
 * Nothing here is optional that the booking flow genuinely needs: a name, a
 * category, somewhere on the map, and opening hours. Everything else can wait
 * until the shop has done its first booking.
 */
export default function ProviderDetailsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const createShop = useCreateShop();
  const { data: serviceTypes } = useServiceTypes();

  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [serviceType, setServiceType] = useState<ServiceType>('barbershop');
  const [address, setAddress] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [phone, setPhone] = useState('');
  const [opening, setOpening] = useState('09:00');
  const [closing, setClosing] = useState('20:00');
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const types = serviceTypes ?? FALLBACK_TYPES;

  async function useDeviceLocation() {
    setLocating(true);
    setError(null);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') {
        setError('Location access is needed so customers can find you.');
        return;
      }
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setLatitude(position.coords.latitude.toFixed(6));
      setLongitude(position.coords.longitude.toFixed(6));
      const place = await Location.reverseGeocodeAsync(position.coords).catch(() => []);
      if (!address) setAddress(place[0]?.city ?? place[0]?.region ?? '');
    } catch {
      setError('Could not read your location. Enter it manually.');
    } finally {
      setLocating(false);
    }
  }

  async function submit() {
    setError(null);

    if (!displayName.trim()) return setError('Give your shop a name.');
    if (!address.trim()) return setError('Add an address customers will recognise.');
    if (!latitude.trim() || !longitude.trim()) return setError('Pin your shop on the map.');
    if (closing.trim() <= opening.trim()) return setError('Closing time must be after opening.');

    try {
      await createShop.mutateAsync({
        display_name: displayName.trim(),
        description: description.trim(),
        service_type: serviceType,
        address: address.trim(),
        contact_phone: phone.trim(),
        opening_time: opening.trim(),
        closing_time: closing.trim(),
        coords: { latitude: Number(latitude), longitude: Number(longitude) },
      });
      router.replace('/(onboarding)/provider-services');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not save your shop.');
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingTop: insets.top + 24,
        paddingBottom: insets.bottom + 24,
        paddingHorizontal: 24,
        gap: 16,
      }}
      keyboardShouldPersistTaps="handled">
      <View className="gap-2">
        <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
          Your shop
        </Text>
        <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
          Customers see this when they search. The name and the category do the
          most work.
        </Text>
      </View>

      <FormError message={error} />

      <Field
        label="Shop name"
        placeholder="Sharp Cuts Studio"
        value={displayName}
        onChangeText={setDisplayName}
        testID="shop-name"
      />

      <View className="gap-2">
        <Text className="text-sm font-medium" style={{ color: colors.textMuted }}>
          What kind of shop is it?
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View className="flex-row gap-2 pr-4">
            {types.map((type) => {
              const selected = type.value === serviceType;
              return (
                <Text
                  key={type.value}
                  onPress={() => setServiceType(type.value)}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  className="rounded-full border px-4 py-2 text-sm font-medium"
                  style={{
                    color: selected ? colors.accentText : colors.text,
                    backgroundColor: selected ? colors.accent : colors.surface,
                    borderColor: selected ? colors.accent : colors.border,
                  }}>
                  {type.label}
                </Text>
              );
            })}
          </View>
        </ScrollView>
      </View>

      <Field
        label="About"
        placeholder="What are you known for?"
        value={description}
        onChangeText={setDescription}
        multiline
        numberOfLines={3}
        testID="shop-about"
      />

      <Field
        label="Address"
        placeholder="Sector 5, New Delhi"
        value={address}
        onChangeText={setAddress}
        testID="shop-address"
      />

      <Button
        variant="secondary"
        icon="locate-outline"
        loading={locating}
        onPress={useDeviceLocation}
        testID="shop-locate">
        Use my current location
      </Button>

      <View className="flex-row gap-3">
        <View className="flex-1">
          <Field
            label="Latitude"
            placeholder="28.6139"
            keyboardType="numbers-and-punctuation"
            value={latitude}
            onChangeText={setLatitude}
            testID="shop-lat"
          />
        </View>
        <View className="flex-1">
          <Field
            label="Longitude"
            placeholder="77.2090"
            keyboardType="numbers-and-punctuation"
            value={longitude}
            onChangeText={setLongitude}
            testID="shop-lng"
          />
        </View>
      </View>

      <Field
        label="Contact number"
        placeholder="+91 98765 43210"
        keyboardType="phone-pad"
        value={phone}
        onChangeText={setPhone}
        testID="shop-phone"
      />

      <View className="flex-row gap-3">
        <View className="flex-1">
          <Field
            label="Opens"
            placeholder="09:00"
            value={opening}
            onChangeText={setOpening}
            testID="shop-opening"
          />
        </View>
        <View className="flex-1">
          <Field
            label="Closes"
            placeholder="20:00"
            value={closing}
            onChangeText={setClosing}
            testID="shop-closing"
          />
        </View>
      </View>

      <Button onPress={submit} loading={createShop.isPending} testID="shop-save" className="mt-2">
        Save and continue
      </Button>
    </ScrollView>
  );
}