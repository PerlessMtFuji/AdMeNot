import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import App from '../App.svelte';
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
  test('simple mode: summary, flagged apps with problems, selection count', async () => {
    const { s } = await scanned();
    expect(screen.getByText(/Aplikacje, które zaśmiecają telefon/)).toBeTruthy();
    const count = Object.keys(s.selection).length;
    expect(screen.getByRole('button', { name: `Napraw zaznaczone (${count})` })).toBeTruthy();
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    const box = screen.getByRole('checkbox', { name: boost.name });
    await fireEvent.click(box);
    expect(screen.getByRole('button', { name: `Napraw zaznaczone (${count - 1})` })).toBeTruthy();
    expect(screen.getAllByText(boost.problems[0], { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('Przedmiot zlecenia')).toBeTruthy();
    expect(screen.getByText(`✓ Bez uwag: ${s.scan!.counts.safe}`)).toBeTruthy();
  });

  test('clean phone', async () => {
    await scanned('clean');
    expect(screen.getByText(/Nie znaleziono podejrzanych aplikacji/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Napraw zaznaczone (0)' }) as HTMLButtonElement)
      .disabled).toBe(true);
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

  test('phone card shows expert details', async () => {
    const { ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByText('R58T00TEST')).toBeTruthy();
    expect(screen.getByText('SM-A145R')).toBeTruthy();
  });
});
