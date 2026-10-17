import { fireEvent, render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { t } from '../lib/i18n/index.svelte';
import { setupCtl } from '../test-utils';
import ManualList from './ManualList.svelte';

const snap = (v: unknown) => JSON.parse(JSON.stringify(v));

// Po skanie serwisant wybrał tryb ręczny (lista dopiero wtedy jest na ekranie, jak w Results).
async function manual() {
  const env = await setupCtl('adware');
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  env.bridge.emit('apk:manual', { scan: { ...snap(env.s.scan), apk_mode: 'manual', on_demand: [] } });
  const view = render(ManualList, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...view, ...env };
}

describe('ManualList', () => {
  it('lista ręczna: wyszukiwanie, systemowe, brak zaznaczania zbiorczego', async () => {
    const { s, getByRole, getByText, queryByRole, getAllByRole } = await manual();
    const user = s.scan!.apps.filter((a) => !a.is_system).length;
    expect(getAllByRole('article')).toHaveLength(user);
    await fireEvent.click(getByRole('checkbox', { name: t('manual.show_system') }));
    expect(getAllByRole('article')).toHaveLength(s.scan!.apps.length);
    const before = getAllByRole('article').length;
    await fireEvent.input(getByRole('searchbox'), { target: { value: 'clean' } });
    expect(getAllByRole('article').length).toBeLessThan(before);
    await fireEvent.input(getByRole('searchbox'), { target: { value: 'zzz-nic-takiego' } });
    expect(getByText(t('manual.empty'))).toBeTruthy();
    // GroupBulk nie istnieje w trybie ręcznym
    expect(queryByRole('checkbox', { name: new RegExp(t('bulk.select_all')) })).toBeNull();
    expect(queryByRole('combobox')).toBeNull();
  });

  it('wiersz przed analizą: bez werdyktu; zaznaczenie liczy czas; po analizie na żądanie werdykt', async () => {
    const { s, ctl, bridge, getByRole } = await manual();
    const flagged = s.scan!.apps.find((a) => a.verdict !== 'safe' && !a.is_system)!;
    const row = () => getByRole('article', { name: flagged.name });
    expect(row().textContent).not.toContain(t('results.why'));
    expect(row().textContent).not.toContain(t(`verdict.${flagged.verdict}`));
    const label = t('manual.analyze_selected', { count: 1, eta: '' }).trim();
    const selected = () => getByRole('button', { name: (name) => name.startsWith(label) });
    await fireEvent.click(getByRole('checkbox', { name: flagged.name }));
    expect(s.selection[flagged.package]).toBeTruthy();
    await vi.waitFor(() => expect(selected().textContent).toContain(t('eta.under_min')));
    await fireEvent.click(selected());
    expect(bridge.calls.find((c) => c.method === 'analyze_selected')?.args[0]).toEqual([flagged.package]);
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'partial', on_demand: [flagged.package] } });
    await tick();
    expect(row().textContent).toContain(t('results.why'));  // AppCard z objawami
    expect(ctl.state.apk.running).toBe(false);
  });
});
