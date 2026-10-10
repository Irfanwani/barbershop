/**
 * The router's front door.
 *
 * Everything the user can see is one of four route groups. This decides which,
 * and keeps deciding — auth state changes, or a token expires mid-session, and
 * the app lands somewhere sensible without the user navigating.
 */

import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { Redirect, router } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { destinationFor, type Destination } from '@/api/endpoints';
import { useColors } from '@/components/ui';
import { useAuthStore } from '@/store/auth';

const WELCOME_SEEN_KEY = '@barbershop/welcome-seen';

const ROUTES: Record<Destination, string> = {
  welcome: '/(auth)/welcome',
  login: '/(auth)/login',
  'verify-email': '/(auth)/verify-email',
  onboarding: '/(onboarding)',
  customer: '/(customer)',
  provider: '/(provider)',
};

export default function Index() {
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const colors = useColors();

  useEffect(() => {
    if (status === 'loading') return;
    const destination = destinationFor(user, true);
    // `(auth)` renders its own first screen; only route outside it.
    if (destination === 'login' || destination === 'verify-email') {
      void AsyncStorage.setItem(WELCOME_SEEN_KEY, '1');
      router.replace(ROUTES[destination]);
    } else if (destination !== 'welcome') {
      router.replace(ROUTES[destination]);
    }
  }, [status, user]);

  if (status === 'loading') {
    return (
      <View className="flex-1 items-center justify-center" style={{ backgroundColor: colors.background }}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return <Redirect href={ROUTES[destinationFor(user, true)]} />;
}