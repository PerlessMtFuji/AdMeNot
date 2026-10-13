import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Zrzuty do README (docs/img/): `npm run readme-shots`. Nie są testem — `npm run e2e` ich nie widzi.
export default defineConfig({ ...base, testDir: 'readme-shots', expect: undefined });
