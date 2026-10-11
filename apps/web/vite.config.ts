import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

/**
 * The marketing site build.
 *
 * This reversed the site's original "no build step" decision, which was the
 * right call while it was one static page and a script. It stopped being right
 * the moment there was a second route: a knowledge base with anchors and deep
 * links wants a router, and hand-rolling history handling to avoid a build is
 * spending effort on the wrong problem. See docs/decisions/0006.
 *
 * `base: './'` keeps asset URLs relative, so `dist/` can be served from a
 * subpath, a CDN, or opened straight off disk.
 */
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
