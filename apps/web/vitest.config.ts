import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

/**
 * Test config kept out of `vite.config.ts` so the two configs cannot disagree
 * about plugins — Vitest reads `vite.config.ts` as the base and this only adds
 * the testing part.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.ts'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/main.tsx', 'src/content/**', 'src/**/*.d.ts'],
        thresholds: {
          // A marketing page that fails to render is a blank page, so the bar
          // is higher than the 75% the API settles for.
          lines: 80,
          statements: 80,
          functions: 75,
          branches: 70,
        },
      },
    },
  }),
);
