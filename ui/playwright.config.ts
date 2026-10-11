import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  // Stały margines na wygładzanie krawędzi; dawne 1% ekranu przepuszczało zmienione ekrany.
  expect: { toHaveScreenshot: { maxDiffPixels: 100 } },
  use: {
    baseURL: 'http://localhost:4173',
    locale: 'pl-PL',
    reducedMotion: 'reduce', // stabilne zrzuty; test ruchu nadpisuje
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: 'npm run build:e2e && npm run preview:e2e',
    url: 'http://localhost:4173',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
