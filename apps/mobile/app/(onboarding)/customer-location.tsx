import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import * as Location from 'expo-location';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { isApiError } from '@/api/client';
import { Button, useColors } from '@/components/ui';
import { Field, FormError } from '@/components/field';
import { useSaveCustomerProfile } from '@/api/hooks';

/**
 * A customer's location.
 *
 * The device's own fix is the easy path and is offered first, because typing an
 * address and hunting for it on a map is nobody's idea of a good afternoon.
 * The manual fields are there for when permission is denied, which happens, and
 * for when someone is booking for a place they are not standing in.
 */
export default function CustomerLocationScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const save = useSaveCustomerProfile();

  const [locating, setLocating] = useState(false);
  const [manual, setManual] = useState(false);
  const [address, setAddress] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function useDeviceLocation() {
    setLocating(true);
    setError(null);

    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') {
        setError('BarberShop needs location access to find shops near you.');
        setManual(true);
        return;
      }

      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      const place = await Location.reverseGeocodeAsync(position.coords).catch(() => []);

      const latitudeText = position.coords.latitude.toFixed(6);
      const longitudeText = position.coords.longitude.toFixed(6);
      setLatitude(latitudeText);
      setLongitude(longitudeText);
      setAddress(place[0]?.city ?? place[0]?.region ?? '');
      setNotice('Found you. Check the pin before saving.');
      setManual(true);
    } catch {
      setError('Could not read your location. Enter it instead.');
      setManual(true);
    } finally {
      setLocating(false);
    }
  }

  async function saveLocation() {
    setError(null);

    if (!latitude.trim() || !longitude.trim()) {
      setError('Add a location so we can show shops near you.');
      return;
    }

    try {
      await save.mutateAsync({
        address: address.trim(),
        coords: {
          latitude: Number(latitude),
          longitude: Number(longitude),
        },
      });
      router.replace('/');
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : 'Could not save your location.');
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
      }}>
      <View className="gap-2">
        <Text className="text-3xl font-bold tracking-tight" style={{ color: colors.text }}>
          Where are you?
        </Text>
        <Text className="text-base leading-6" style={{ color: colors.textMuted }}>
          We sort shops by real distance, so this is what makes the list useful.
        </Text>
      </View>

      <FormError message={error} />
      {notice ? (
        <Text className="text-sm" style={{ color: colors.success }}>
          {notice}
        </Text>
      ) : null}

      <Button
        variant="secondary"
        icon="locate-outline"
        loading={locating}
        onPress={useDeviceLocation}
        testID="location-detect">
        Use my current location
      </Button>

      {manual ? (
        <View className="gap-4">
          <Field
            label="Address"
            placeholder="Where is that?"
            value={address}
            onChangeText={setAddress}
            testID="location-address"
          />
          <View className="flex-row gap-3">
            <View className="flex-1">
              <Field
                label="Latitude"
                placeholder="28.6139"
                keyboardType="numbers-and-punctuation"
                value={latitude}
                onChangeText={setLatitude}
                testID="location-lat"
              />
            </View>
            <View className="flex-1">
              <Field
                label="Longitude"
                placeholder="77.2090"
                keyboardType="numbers-and-punctuation"
                value={longitude}
                onChangeText={setLongitude}
                testID="location-lng"
              />
            </View>
          </View>
        </View>
      ) : null}

      <Button
        onPress={saveLocation}
        loading={save.isPending}
        disabled={!manual}
        testID="location-save">
        Save and continue
      </Button>
    </ScrollView>
  );
}