import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { setupCtl } from '../test-utils';

test('history lists the order, restores one action and undoes the whole order', async () => {
  const { ctl, s, bridge } = await setupCtl('adware');
  render(App, { props: { ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  await vi.waitFor(() => expect(s.history).not.toBeNull());
  await tick();
  const order = s.history!.orders[0];
  expect(screen.getByText(order.number)).toBeTruthy();
  expect(screen.getByText(/Anna K\./)).toBeTruthy();
  const restore = screen.getAllByRole('button', { name: /Przywróć/ });
  expect(restore.length).toBe(order.actions.filter((a) => a.status === 'done').length);
  await fireEvent.click(restore[0]);
  expect(bridge.calls.at(-1)).toEqual({ method: 'undo', args: [order.number, order.actions.find(
    (a) => a.status === 'done')!.id, null] });
  await vi.waitFor(() => expect(s.undoResult).not.toBeNull());
  await tick();
  expect(screen.getByRole('status').textContent).toContain('cofnięte');
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  expect(s.screen).toBe('main');
});

test('interrupted orders can be finished from history', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = { serial: 'S1', serials: ['S1', 'S2'], devices: [], orders: [{
    id: 1, number: 'ZS/2026/0926/05', created_at: '2026-09-26T14:30', status: 'running',
    status_label: 'w toku', client: null, model: 'SM-A145R', interrupted: true,
    actions: [{ id: 3, package: 'p', level: 'disable', level_label: 'WYŁĄCZ', kind: 'enabled',
      step_label: 'wyłączenie aplikacji', status: 'pending', status_label: 'oczekuje', error: null }],
  }] };
  s.screen = 'history';
  await tick();
  expect(screen.getByText('Przerwane')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Dokończ' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'resume', args: ['ZS/2026/0926/05'] });
  await fireEvent.change(screen.getByRole('combobox', { name: 'Telefon' }), { target: { value: 'S2' } });
  expect(bridge.calls.at(-1)).toEqual({ method: 'history', args: ['S2'] });
});
