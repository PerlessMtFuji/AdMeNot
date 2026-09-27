import { describe, expect, test } from 'vitest';
import { USB_GROUPS, USB_STEPS } from '../usb';
import en from './en.json';
import { ERROR_KEYS, i18n, LEVEL_KEYS, MATCH_KEYS, SCAN_STAGES, t } from './index.svelte';
import pl from './pl.json';

function flat(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === 'object' && v !== null ? flat(v as Record<string, unknown>, `${prefix}${k}.`)
      : [`${prefix}${k}`]);
}

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
      ...SCAN_STAGES.map((k) => `scan.stage.${k}`),
      ...LEVEL_KEYS.map((k) => `level.${k}`),
      ...MATCH_KEYS.map((k) => `match.${k}`),
      ...USB_GROUPS.map((g) => `usb.group.${g}`),
      ...USB_GROUPS.flatMap((g) => Array.from({ length: USB_STEPS[g] }, (_, i) => `usb.${g}.s${i + 1}`)),
    ];
    expect(wanted.filter((k) => !keys.has(k))).toEqual([]);
  });

  test('t() switches language and fills parameters', () => {
    i18n.lang = 'pl';
    expect(t('actions.fix', { count: 2 })).toBe('Napraw zaznaczone (2)');
    i18n.lang = 'en';
    expect(t('actions.fix', { count: 2 })).toBe('Fix selected (2)');
    expect(t('no.such.key')).toBe('no.such.key');
    i18n.lang = 'pl';
  });
});
