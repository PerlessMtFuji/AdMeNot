import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { t, tp } from '../lib/i18n/index.svelte';
import { setupCtl } from '../test-utils';

async function scanned(scenario = 'adware') {
  const env = await setupCtl(scenario);
  render(App, { props: { ctl: env.ctl } });
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  await tick();
  return env;
}

describe('Results', () => {
  test('simple mode: title, symptom rows, action switch, plan panel and safe list', async () => {
    const { s } = await scanned();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    expect(screen.getByRole('heading', { name: tp('results.title', flagged.length) })).toBeTruthy();
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    const card = screen.getByRole('article', { name: boost.name });
    expect(within(card).getByText(t(`category.${boost.symptoms[0].category}`))).toBeTruthy();
    expect(within(card).getByText(boost.symptoms[0].text)).toBeTruthy();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    const count = Object.keys(s.selection).length;
    expect(within(panel).getByRole('button', { name: `Napraw zaznaczone (${count})` })).toBeTruthy();
    expect(within(panel).getByText(boost.name)).toBeTruthy();
    await fireEvent.click(within(card).getByRole('button', { name: 'Wyłącz' }));
    expect(s.selection[boost.package]).toBe('disable');
    await fireEvent.click(within(card).getByRole('checkbox', { name: boost.name }));
    expect(s.selection[boost.package]).toBeUndefined();
    expect(within(panel).getByRole('button', { name: `Napraw zaznaczone (${count - 1})` })).toBeTruthy();
    expect(within(panel).getByText('R58T00TEST')).toBeTruthy();
    await fireEvent.click(within(panel).getByRole('button', { name: new RegExp(tp('results.safe', s.scan!.counts.safe)) }));
    const safe = screen.getByRole('list', { name: 'Aplikacje bez uwag' });
    expect(safe.querySelectorAll('li')).toHaveLength(s.scan!.counts.safe);
  });

  test('nothing selected: the panel says so and the fix button is disabled', async () => {
    const { s } = await scanned();
    s.selection = {};
    await tick();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    expect(within(panel).getByText('Zaznacz aplikacje, które chcesz naprawić.')).toBeTruthy();
    const fix = within(panel).getByRole('button', { name: 'Napraw zaznaczone (0)' }) as HTMLButtonElement;
    expect(fix.disabled).toBe(true);
  });

  test('clean phone', async () => {
    const { s } = await scanned('clean');
    expect(screen.getByRole('heading', { name: 'Nie znaleziono problemów' })).toBeTruthy();
    expect(screen.getByText(`Sprawdzone aplikacje: ${s.scan!.counts.total}`)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Napraw zaznaczone (0)' }) as HTMLButtonElement)
      .disabled).toBe(true);
  });

  test('mode switch in the header', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: 'Ekspert' }));
    await vi.waitFor(() => expect(s.settings.mode).toBe('expert'));
  });

  test('expert mode: table, search, action select, evidence, show all', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByRole('columnheader', { name: 'Aplikacja / pakiet' })).toBeTruthy();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe').length;
    expect(screen.getAllByRole('row')).toHaveLength(flagged + 1);
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'forecast' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    await fireEvent.change(screen.getByRole('combobox', { name: 'Akcja com.wlive.forecast' }),
      { target: { value: 'silence' } });
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await fireEvent.click(screen.getByRole('button', { expanded: false }));
    const wlive = s.scan!.apps.find((a) => a.package === 'com.wlive.forecast')!;
    expect(screen.getByText(wlive.findings[0].rule_id)).toBeTruthy();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Pokaż wszystkie aplikacje' }));
    expect(screen.getAllByRole('row')).toHaveLength(s.scan!.apps.length + 1);
    expect(screen.getByRole('button', { name: 'Konsola ADB' })).toBeTruthy();
  });
});
