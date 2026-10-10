/**
 * The root layout: providers, theming, and the auth bootstrap.
 *
 * Order matters here. The HTTP client has to know where to find the token before
 * any query fires, and the token is only known after the secure store has been
 * read — so bootstrap runs before the navigator mounts anything that queries.
 */

import '../global.css';

import { useEffect, useRef } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { configureClient } from '@/api/client';
import { queryClient } from '@/lib/query-client';
import { useAuthStore } from '@/store/auth';

void SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const scheme = useColorScheme();
  const bootstrap = useAuthStore((state) => state.bootstrap);
  const signOut = useAuthStore((state) => state.signOut);
  const bootstrapped = useRef(false);

  useEffect(() => {
    // Wire the client to the store once, at the top of the tree.
    configureClient({
      getToken: () => useAuthStore.getState().token,
      // The server decides a token is dead; the store decides what that means.
      onUnauthorized: () => {
        void signOut();
      },
    });
  }, [signOut]);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    // Hold the splash until the token has been read, so the app never flashes
    // the welcome screen at someone who is already signed in.
    if (useAuthStore.getState().status !== 'loading') void SplashScreen.hideAsync();
  }, []);

  useEffect(() => {
    const unsubscribe = useAuthStore.subscribe((state) => {
      if (state.status !== 'loading') void SplashScreen.hideAsync();
    });
    return unsubscribe;
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
          <Stack
            screenOptions={{
              headerShown: false,
              animation: 'slide_from_right',
              contentStyle: { backgroundColor: scheme === 'dark' ? '#0F172A' : '#FFFFFF' },
            }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="(auth)" />
            <Stack.Screen name="(onboarding)" />
            <Stack.Screen name="settings" />
            <Stack.Screen name="(customer)" />
            <Stack.Screen name="(provider)" />
          </Stack>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

export { router };