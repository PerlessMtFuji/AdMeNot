import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { setupCtl } from '../test-utils';
import ApkProgress from './ApkProgress.svelte';

const GB = 1024 ** 3;

async function mount(effective: number) {
  const env = await setupCtl('adware');
  env.s.apk = { done: 5, total: 140, running: true, changed: [], eta: null };
  env.s.apkEstimate = { to_fetch_bytes: 7.2 * GB, total_bytes: 7.2 * GB, apps: 142, unknown: 0, cached: 0,
    largest_bytes: 3 * GB, limit_bytes: 10 * GB, effective_bytes: effective, free_bytes: 4 * GB,
    eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null };
  render(ApkProgress, { context: new Map([['ctl', env.ctl]]) });
  await tick();
}

test('hint trigger is a button named after the estimate', async () => {
  await mount(20 * GB);
  const btn = screen.getByRole('button', { name: /Analiza pobierze ok\. 7,2 GB/ });
  expect(btn.tagName).toBe('BUTTON');
  expect(btn.getAttribute('type')).toBe('button');
});

test('icon is tinted as a warning only when the estimate exceeds the disk space', async () => {
  await mount(2 * GB);
  const over = screen.getByRole('button', { name: /Analiza pobierze/ }).querySelector('svg')!;
  expect(over.getAttribute('class')).toContain('text-warn');
});

test('icon has no warning tint when the estimate fits', async () => {
  await mount(20 * GB);
  const ok = screen.getByRole('button', { name: /Analiza pobierze/ }).querySelector('svg')!;
  expect(ok.getAttribute('class')).not.toContain('text-warn');
});
