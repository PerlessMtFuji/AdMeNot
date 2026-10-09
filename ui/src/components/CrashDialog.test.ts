import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { setupCtl } from '../test-utils';

async function withError() {
  const env = await setupCtl('empty');
  render(App, { props: { ctl: env.ctl } });
  env.s.error = { key: 'internal', message: 'KeyError', crash: '20261009-140312-abcd' };
  await tick();
  return env;
}

test('error card opens the dialog with a preview and sends', async () => {
  const { bridge } = await withError();
  await fireEvent.click(screen.getByRole('button', { name: 'Wyślij raport' }));
  const dialog = await screen.findByRole('dialog', { name: 'Wyślij raport o błędzie' });
  const adb = screen.getByRole('checkbox', { name: /Dołącz ostatnie polecenia ADB/ }) as HTMLInputElement;
  expect(adb.checked).toBe(false);
  await fireEvent.click(screen.getByText('Pokaż, co zostanie wysłane'));
  await vi.waitFor(() => expect(dialog.textContent).toContain('"KeyError"'));
  await fireEvent.click(adb);
  await vi.waitFor(() => expect(dialog.textContent).toContain('shell:pm list packages'));
  await fireEvent.click(screen.getByRole('button', { name: 'Wyślij' }));
  expect(await screen.findByText('Wysłano. Numer raportu: R-7K3Q9M')).toBeTruthy();
  expect(bridge.calls.find((c) => c.method === 'send_crash')?.args).toEqual(['20261009-140312-abcd', true, '']);
});

test('offline message keeps the report', async () => {
  const { bridge } = await withError();
  bridge.failNextCrashSend('crash_offline');
  await fireEvent.click(screen.getByRole('button', { name: 'Wyślij raport' }));
  await fireEvent.click(await screen.findByRole('button', { name: 'Wyślij' }));
  expect(await screen.findByText('Nie udało się połączyć z serwerem. Raport czeka — spróbuj później.')).toBeTruthy();
});

test('startup banner after a crash, not over the update banner', async () => {
  const env = await setupCtl('empty');
  env.bridge.setCrashes([], ['20261009-140312-abcd']);
  await env.ctl.loadCrashes();
  render(App, { props: { ctl: env.ctl } });
  expect(await screen.findByText('Program ostatnio zakończył się błędem. Wysłać raport?')).toBeTruthy();
  env.bridge.emit('update:state', { available: { version: '9.9.9', notes: '', size: 1 }, dismissed: false,
    retired: null, updated_to: null, updated_notes: null, installable: true });
  await tick();
  expect(screen.queryByText('Program ostatnio zakończył się błędem. Wysłać raport?')).toBeNull();
});

test('banner dismiss discards the report', async () => {
  const env = await setupCtl('empty');
  env.bridge.setCrashes([], ['20261009-140312-abcd']);
  await env.ctl.loadCrashes();
  render(App, { props: { ctl: env.ctl } });
  await fireEvent.click(await screen.findByRole('button', { name: 'Odrzuć' }));
  expect(env.bridge.calls.at(-1)).toEqual({ method: 'discard_crash', args: ['20261009-140312-abcd'] });
  await tick();
  expect(screen.queryByText('Program ostatnio zakończył się błędem. Wysłać raport?')).toBeNull();
});

test('ADB box is disabled without ADB lines', async () => {
  const env = await withError();
  env.ctl.openCrash('20261009-140312-abcd');
  await vi.waitFor(() => expect(env.s.crashPreview).not.toBeNull());
  env.s.crashHasAdb = false;
  await tick();
  expect((screen.getByRole('checkbox', { name: /Dołącz/ }) as HTMLInputElement).disabled).toBe(true);
});
