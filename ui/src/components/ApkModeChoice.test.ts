import { fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { t } from '../lib/i18n/index.svelte';
import { renderWith } from '../test-utils';
import ApkModeChoice from './ApkModeChoice.svelte';

// Po skanie: pytanie o tryb należy do bieżącej analizy APK (zadanie j1).
async function asked() {
  const env = await renderWith(ApkModeChoice, 'adware');
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  env.s.job = { id: 'j1', kind: 'apk' };
  return env;
}

describe('ApkModeChoice', () => {
  it('pokazuje oba wybory z czasem i odpowiada', async () => {
    const { bridge, getByRole, getByText } = await asked();
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 143, to_fetch_bytes: 1.8 * 1024 ** 3,
      total_bytes: 2 * 1024 ** 3, cached: 40, unknown: 0, largest_bytes: 0, limit_bytes: 0, effective_bytes: 0, free_bytes: 0,
      eta_s: 720, eta_kind: 'measured', eta_min_s: 720, eta_max_s: 720 });
    await tick();
    expect(getByText(/143 aplikacje · .* do pobrania \(40 już w pamięci\)/)).toBeTruthy();
    const full = getByRole('button', { name: new RegExp(t('apk_mode.full')) });
    expect(full.textContent).toContain(t('eta.min', { n: 12 }));
    expect(full.textContent).not.toContain(t('eta.rough'));
    expect(getByRole('button', { name: new RegExp(t('apk_mode.manual')) }).textContent).toContain(t('eta.now'));
    await fireEvent.click(getByRole('button', { name: new RegExp(t('apk_mode.manual')) }));
    expect(bridge.calls.some((c) => c.method === 'answer' && c.args[1] === 'manual')).toBe(true);
    expect(bridge.calls.some((c) => c.method === 'save_settings')).toBe(false);
  });

  it('przy szacunku orientacyjnym przedział i dopisek, bez szacunku „czas nieznany”', async () => {
    const { bridge, getByRole } = await asked();
    const full = () => getByRole('button', { name: new RegExp(t('apk_mode.full')) }).textContent ?? '';
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 143,
      eta_s: 600, eta_kind: 'rough', eta_min_s: 360, eta_max_s: 900 });
    await tick();
    expect(full()).toContain(t('eta.range', { lo: 6, hi: 15 }));
    expect(full()).toContain(t('eta.rough'));
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 143,
      eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null });
    await tick();
    expect(full()).toContain(t('eta.unknown'));
    expect(full()).not.toContain(t('eta.rough'));
  });

  it('„Zapamiętaj wybór” zapisuje ustawienie', async () => {
    const { bridge, getByRole } = await asked();
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 30, eta_kind: 'measured', eta_min_s: 30, eta_max_s: 30 });
    await tick();
    await fireEvent.click(getByRole('checkbox', { name: t('apk_mode.remember') }));
    await fireEvent.click(getByRole('button', { name: new RegExp(t('apk_mode.full')) }));
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'answer' && c.args[1] === 'full')).toBe(true));
    expect(bridge.calls.some((c) => c.method === 'save_settings'
      && (c.args[0] as { apk_mode_default?: string }).apk_mode_default === 'full')).toBe(true);
  });
});
