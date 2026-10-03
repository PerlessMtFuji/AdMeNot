import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

// Build produkcyjny trafia do pakietu Pythona; build e2e (z atrapą mostu) zostaje w ui/dist-e2e.
export default defineConfig(({ mode }) => ({
  plugins: [tailwindcss(), svelte()],
  base: './',
  build: {
    outDir: mode === 'e2e' ? 'dist-e2e' : '../src/admenot/app/web',
    emptyOutDir: true,
    target: 'es2022',
  },
  server: { fs: { allow: ['..'] } }, // atrapa mostu czyta tests/fixtures/bridge
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.ts'],
  },
}));
