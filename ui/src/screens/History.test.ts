import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { groupHistory } from '../lib/logic';
import type { HistoryView } from '../lib/types';
import { setupCtl } from '../test-utils';

async function openHistory(scenario = 'adware') {
  const env = await setupCtl(scenario);
  render(App, { props: { ctl: env.ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  await vi.waitFor(() => expect(env.s.history).not.toBeNull());
  await tick();
  return env;
}

test('history: order card says what happened and restores a whole app', async () => {
  const { s, bridge } = await openHistory();
  const order = s.history!.orders[0];
  const card = screen.getByRole('article', { name: order.number });
  expect(card.textContent).toContain('Usunięto 1 aplikację i wyłączono 1 aplikację');
  expect(card.textContent).toContain('Anna K.');
  const rows = groupHistory(order.actions);
  const restore = within(card).getAllByRole('button', { name: /^Przywróć / });
  expect(restore).toHaveLength(rows.filter((r) => r.canRestore).length);
  await fireEvent.click(restore[0]);
  expect(bridge.calls.at(-1)).toEqual({ method: 'undo', args: [order.number, null, rows[0].package] });
  await vi.waitFor(() => expect(s.undoResult).not.toBeNull());
  await tick();
  expect(screen.getAllByRole('status').some((el) => el.textContent?.includes('cofnięte'))).toBe(true);
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  expect(s.screen).toBe('main');
});

test('history: steps of an app can be restored one by one', async () => {
  const { s, bridge } = await openHistory();
  const order = s.history!.orders[0];
  const card = screen.getByRole('article', { name: order.number });
  await fireEvent.click(within(card).getAllByRole('button', { name: 'Kroki' })[0]);
  const first = groupHistory(order.actions)[0];
  const stepButtons = within(card).getAllByRole('button', { name: '↶ Przywróć' });
  expect(stepButtons).toHaveLength(first.actions.filter((a) => a.status === 'done').length);
  await fireEvent.click(stepButtons[0]);
  expect(bridge.calls.at(-1)).toEqual({ method: 'undo',
    args: [order.number, first.actions.find((a) => a.status === 'done')!.id, null] });
});

function view(over: Partial<HistoryView['orders'][number]>): HistoryView {
  return { serial: 'S1', serials: ['S1', 'S2'], devices: [{ serial: 'S1', name: 'Samsung Galaxy A14', model: 'SM-A145R', image: '' },
    { serial: 'S2', name: 'S2', model: null, image: '' }],
    orders: [{ id: 1, number: 'ZS/2026/0926/05', created_at: '2026-09-26T14:30', status: 'running',
      status_label: 'w toku', client: null, model: 'SM-A145R', interrupted: true, screenshots: 0,
      actions: [
        { id: 2, package: 'p', level: 'disable', level_label: 'WYŁĄCZ', kind: 'notif', step_label: 'odebranie zgody',
          status: 'done', status_label: 'wykonane', error: null },
        { id: 3, package: 'p', level: 'disable', level_label: 'WYŁĄCZ', kind: 'enabled', step_label: 'wyłączenie aplikacji',
          status: 'pending', status_label: 'oczekuje', error: null }],
      ...over }] };
}

test('interrupted order: one banner with the progress, finish it, switch phones', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = view({});
  s.screen = 'history';
  await tick();
  expect(screen.getByText(/nie zostało dokończone/)).toBeTruthy();
  expect(screen.getByText('p — wykonano 1 z 2 kroków.')).toBeTruthy();
  expect(screen.getByRole('article', { name: 'ZS/2026/0926/05' }).textContent).toContain('Przerwane: p');
  await fireEvent.click(screen.getByRole('button', { name: 'Dokończ' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'resume', args: ['ZS/2026/0926/05'] });
  await fireEvent.click(screen.getByRole('button', { name: /S2/ }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'history', args: ['S2'] });
  await fireEvent.input(screen.getByLabelText('Inny numer seryjny…'), { target: { value: 'X9' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Pokaż' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'history', args: ['X9'] });
});

test('partially undone order: restored app has no restore, others keep it; client shown literally', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = view({ status: 'partially_undone', status_label: 'częściowo cofnięte', interrupted: false,
    client: '<img src=x onerror=alert(1)>', actions: [
      { id: 1, package: 'a.one', level: 'disable', level_label: 'WYŁĄCZ', kind: 'enabled', step_label: 'wyłączenie',
        status: 'undone', status_label: 'cofnięte', error: null },
      { id: 2, package: 'b.two', level: 'remove', level_label: 'USUŃ', kind: 'installed', step_label: 'odinstalowanie',
        status: 'done', status_label: 'wykonane', error: null }] });
  s.screen = 'history';
  await tick();
  const card = screen.getByRole('article', { name: 'ZS/2026/0926/05' });
  expect(card.className).not.toContain('border-dashed');
  expect(within(card).getByText('przywrócona')).toBeTruthy();
  expect(within(card).queryByRole('button', { name: 'Przywróć a.one' })).toBeNull();
  expect(within(card).getByRole('button', { name: 'Przywróć b.two' })).toBeTruthy();
  expect(card.querySelector('img')).toBeNull();
  expect(within(card).getByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy();
});

test('history: report button next to each order', async () => {
  const { s, ctl, bridge } = await setupCtl('report');
  render(App, { props: { ctl } });
  await ctl.startScan();
  await vi.waitFor(() => expect(s.job).toBeNull());
  await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
  await fireEvent.click(await screen.findByRole('button', { name: /^Wykonaj/ }));
  await vi.waitFor(() => expect(s.phase).toBe('done'));
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  const order = await screen.findByRole('article', { name: s.result!.order });
  await fireEvent.click(within(order).getByRole('button', { name: 'Protokół PDF' }));
  await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'report')).toBe(true));
});

test('history: phone list shows the phone name first, the model below and the phone photo', async () => {
  const { s } = await openHistory();
  const d = s.history!.devices[0];
  const panel = screen.getByRole('complementary', { name: 'Telefon' });
  const row = within(panel).getByRole('button', { name: new RegExp(`^${d.name}`) });
  const lines = [...row.querySelectorAll('b, span.text-xs')].map((el) => el.textContent);
  expect(lines.slice(0, 2)).toEqual([d.name, d.model]);
  expect(within(row).getByRole('img', { name: d.name }).getAttribute('src')).toBe(d.image);
});
