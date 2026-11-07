import { describe, expect, test } from 'vitest';
import { FILTERS } from '../explorer/logic';
import { USB_GROUPS, USB_STEPS, type UsbGroup } from '../usb';
import en from './en.json';
import { CRASH_ERROR_KEYS, ERROR_KEYS, i18n, LEVEL_KEYS, PLURAL_KEYS, RESTORE_ERROR_KEYS, SCAN_STAGES, t, tp, UPDATE_ERROR_KEYS } from './index.svelte';
import pl from './pl.json';

function flat(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null ? flat(v as Record<string, unknown>, `${prefix}${k}.`)
      : [`${prefix}${k}`]);
}

// `optional` to tylko plakietka (connect.guide_optional), bez własnego tekstu w kroku.
const usbStepKeys = (g: UsbGroup) => USB_STEPS[g].flatMap((parts, i) =>
  ['act', ...parts.filter((p) => p !== 'optional')].map((p) => `usb.${g}.s${i + 1}.${p}`));

const sources = import.meta.glob('../../**/*.{svelte,ts}', {
  eager: true, query: '?raw', import: 'default',
}) as Record<string, string>;

describe('dictionaries', () => {
  test('PL and EN have the same keys', () => {
    expect(flat(en).sort()).toEqual(flat(pl).sort());
  });

  test('every literal t() key exists', () => {
    const keys = new Set(flat(pl));
    const missing: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (file.endsWith('.test.ts')) continue;
      for (const m of text.matchAll(/\bt\(\s*'([a-z_]+(?:\.[a-z0-9_]+)+)'/g)) {
        if (!keys.has(m[1])) missing.push(`${file}: ${m[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });

  test('dynamic key families exist', () => {
    const keys = new Set(flat(pl));
    const wanted = [
      ...ERROR_KEYS.map((k) => `error.${k}`),
      ...UPDATE_ERROR_KEYS.map((k) => `update.error.${k}`),
      ...CRASH_ERROR_KEYS.map((k) => `crash.error.${k}`),
      ...RESTORE_ERROR_KEYS.map((k) => `transfer.restore.error.${k}`),
      ...SCAN_STAGES.map((k) => `scan.stage.${k}`),
      ...LEVEL_KEYS.map((k) => `level.${k}`),
      ...USB_GROUPS.map((g) => `usb.group.${g}`),
      ...USB_GROUPS.flatMap(usbStepKeys),
      ...['ads', 'notif', 'removal', 'data', 'disguise', 'background', 'origin', 'combo']
        .map((c) => `category.${c}`),
      ...['camera', 'screenshots', 'downloads', 'whatsapp', 'movies', 'music', 'documents', 'all']
        .map((p) => `explorer.place.${p}`),
      ...FILTERS.map((f) => `explorer.filter.${f}`),
      ...['grid', 'list'].map((v) => `explorer.view.${v}`),
      ...['on', 'off'].map((v) => `explorer.peek.${v}`),
      ...['name', 'size', 'date'].map((c) => `explorer.list.${c}`),
      ...['busy', 'other_phone', 'switched'].map((n) => `explorer.notice.${n}`),
    ];
    expect(wanted.filter((k) => !keys.has(k))).toEqual([]);
  });

  test('USB guide steps have only the parts declared in USB_STEPS', () => {
    expect(flat(pl).filter((k) => /^usb\.[a-z]+\.s\d/.test(k)).sort())
      .toEqual(USB_GROUPS.flatMap(usbStepKeys).sort());
  });

  test('every translated error key reaches the error card', () => {
    const ui = new Set(['fatal', 'restart', 'log']);
    const known: readonly string[] = ERROR_KEYS;
    const unused = Object.keys(pl.error).filter((k) => !ui.has(k) && !known.includes(k));
    expect(unused).toEqual([]);
  });

  test('t() switches language and fills parameters', () => {
    i18n.lang = 'pl';
    expect(t('actions.fix', { count: 2 })).toBe('Podsumowanie (2)');
    i18n.lang = 'en';
    expect(t('actions.fix', { count: 2 })).toBe('Summary (2)');
    expect(t('no.such.key')).toBe('no.such.key');
    i18n.lang = 'pl';
  });

  test('plural families have every form', () => {
    const keys = new Set(flat(pl));
    const wanted = PLURAL_KEYS.flatMap((k) => ['one', 'few', 'many', 'other'].map((f) => `${k}.${f}`));
    expect(wanted.filter((k) => !keys.has(k))).toEqual([]);
  });

  test('tp() picks the Polish and English plural form', () => {
    i18n.lang = 'pl';
    expect(tp('results.title', 1)).toBe('1 aplikacja wymaga uwagi');
    expect(tp('results.title', 3)).toBe('3 aplikacje wymagają uwagi');
    expect(tp('results.title', 5)).toBe('5 aplikacji wymaga uwagi');
    expect(tp('results.title', 22)).toBe('22 aplikacje wymagają uwagi');
    i18n.lang = 'en';
    expect(tp('results.title', 1)).toBe('1 app needs attention');
    expect(tp('results.title', 3)).toBe('3 apps need attention');
    i18n.lang = 'pl';
  });
});
