import { readdirSync, readFileSync } from 'node:fs';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

// Okno ma most do metod uruchamiających programy (check_adb, adb_path, adb_shell): gdyby kiedyś
// trafił się wstrzyknięty HTML, CSP nie pozwoli wykonać obcego skryptu (przegląd 2026-10-11).
// Style inline: przejścia Svelte i atrybuty style. Obrazy data: — ikony aplikacji i zrzuty ekranu.
// Eksplorator plików: miniatury, podgląd i strumienie z lokalnego serwera mediów (127.0.0.1, losowy port), blob: z pamięci.
const CSP = [
  "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: http://127.0.0.1:*", "media-src http://127.0.0.1:* blob:", "font-src 'self' data: blob:",
  "connect-src 'self' http://127.0.0.1:*",
  "object-src 'none'", "base-uri 'none'", "form-action 'none'",
].join('; ');

const csp = {
  name: 'admenot-csp',
  apply: 'build' as const,
  transformIndexHtml: (html: string) =>
    html.replace('<head>', `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
};

// pdf.js czyta te pliki w czasie pracy (dekodery skanów, mapy znaków, czcionki), nie importuje ich.
const pdfjsAssets = {
  name: 'admenot-pdfjs-assets',
  apply: 'build' as const,
  generateBundle(this: { emitFile(file: { type: 'asset'; fileName: string; source: Uint8Array }): void }) {
    for (const dir of ['wasm', 'cmaps', 'standard_fonts', 'iccs']) {
      const from = new URL(`./node_modules/pdfjs-dist/${dir}/`, import.meta.url);
      for (const name of readdirSync(from)) {
        this.emitFile({ type: 'asset', fileName: `pdfjs/${dir}/${name}`, source: readFileSync(new URL(name, from)) });
      }
    }
  },
};

// Build produkcyjny trafia do pakietu Pythona; build e2e (z atrapą mostu) zostaje w ui/dist-e2e.
export default defineConfig(({ mode }) => ({
  plugins: [tailwindcss(), svelte(), csp, pdfjsAssets],
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
