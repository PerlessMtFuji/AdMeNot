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
  test('header shows the phone thumbnail next to the device name, in both modes', async () => {
    const { ctl, s } = await scanned();
    const header = screen.getByRole('main').querySelector('header')!;
    const img = within(header).getByRole('img', { name: s.device!.name });
    expect(img.getAttribute('src')).toBe(s.device!.image);
    ctl.setMode('expert');
    await tick();
    expect(within(screen.getByRole('main').querySelector('header')!).getByRole('img', { name: s.device!.name })).toBeTruthy();
  });

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

  test('expert mode: tiles, filter, search, keyboard, evidence panel', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByRole('columnheader', { name: 'Aplikacja' })).toBeTruthy();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    expect(screen.getAllByRole('row')).toHaveLength(flagged.length + 1);
    const panel = screen.getByRole('complementary', { name: 'Szczegóły aplikacji' });
    expect(within(panel).getByText(flagged[0].name)).toBeTruthy();
    expect(panel.textContent).not.toMatch(/DM-/);
    const table = screen.getByRole('group', { name: 'Tabela aplikacji' });
    await fireEvent.keyDown(table, { key: 'ArrowDown' });
    expect(s.focused).toBe(flagged[1].package);
    for (let i = 0; i < flagged.length + 2; i++) await fireEvent.keyDown(table, { key: 'ArrowDown' });
    expect(s.focused).toBe(flagged.at(-1)!.package);
    const before = s.focused! in s.selection;
    await fireEvent.keyDown(table, { key: ' ' });
    expect(s.focused! in s.selection).toBe(!before);
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'forecast' } });
    expect(screen.getAllByRole('row')).toHaveLength(2);
    expect(within(panel).getByText('com.wlive.forecast')).toBeTruthy();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'zzz-nothing' } });
    expect(screen.getAllByRole('row')).toHaveLength(1);
    expect(within(panel).getByText('Wybierz aplikację w tabeli.')).toBeTruthy();
    await fireEvent.keyDown(table, { key: 'ArrowUp' });
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Akcja com.wlive.forecast' }),
      { target: { value: 'silence' } });
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await fireEvent.click(screen.getByRole('button', { name: `Wszystkie · ${s.scan!.apps.length}` }));
    expect(screen.getAllByRole('row')).toHaveLength(s.scan!.apps.length + 1);
  });
  test('expert table: keys typed in a row control stay there, arrows keep the focused row in view', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    const focused = s.focused ?? flagged[0].package;
    const other = flagged.find((a) => a.package !== focused)!;
    const selected = focused in s.selection;
    await fireEvent.keyDown(screen.getByRole('checkbox', { name: other.package }), { key: ' ' });
    expect(focused in s.selection).toBe(selected);
    await fireEvent.keyDown(screen.getByRole('combobox', { name: `Akcja ${focused}` }), { key: 'ArrowDown' });
    expect(s.focused ?? flagged[0].package).toBe(focused);
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');
    await fireEvent.keyDown(screen.getByRole('group', { name: 'Tabela aplikacji' }), { key: 'ArrowDown' });
    await tick();
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
    expect((scroll.mock.contexts.at(-1) as HTMLElement).getAttribute('aria-selected')).toBe('true');
    scroll.mockRestore();
  });
});
