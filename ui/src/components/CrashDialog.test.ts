import { fireEvent, render, screen, within } from '@testing-library/svelte';
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

test('offline: the report is queued and the dialog only offers closing', async () => {
  const { bridge, s } = await withError();
  bridge.failNextCrashSend('crash_offline');
  await fireEvent.click(screen.getByRole('button', { name: 'Wyślij raport' }));
  await fireEvent.click(await screen.findByRole('button', { name: 'Wyślij' }));
  const notice = await screen.findByRole('status');
  expect(within(notice).getByText('Brak połączenia z serwerem')).toBeTruthy();
  expect(within(notice).getByText('Raport zostanie wysłany automatycznie, gdy połączenie wróci. Możesz zamknąć to okno.')).toBeTruthy();
  const dialog = within(screen.getByRole('dialog'));
  expect(dialog.queryByRole('button', { name: 'Wyślij' })).toBeNull();
  await fireEvent.click(dialog.getByRole('button', { name: 'Zamknij' }));
  expect(s.crashDialog).toBeNull();
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

async function sentDialog() {
  await withError();
  await fireEvent.click(screen.getByRole('button', { name: 'Wyślij raport' }));
  await fireEvent.click(await screen.findByRole('button', { name: 'Wyślij' }));
  await screen.findByText('Wysłano. Numer raportu: R-7K3Q9M');
}

test('copy shows feedback', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
  try {
    await sentDialog();
    await fireEvent.click(screen.getByRole('button', { name: 'Kopiuj' }));
    expect(await screen.findByText('Skopiowano')).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith('R-7K3Q9M');
  } finally {
    vi.unstubAllGlobals();
  }
});

test('copy rejected by the clipboard does not leak a rejection', async () => {
  const rejections: unknown[] = [];
  const onRejection = (reason: unknown) => rejections.push(reason);
  process.on('unhandledRejection', onRejection);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: () => Promise.reject(new Error('denied')) } });
  try {
    await sentDialog();
    await fireEvent.click(screen.getByRole('button', { name: 'Kopiuj' }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(rejections).toEqual([]);
    expect(screen.getByText('Wysłano. Numer raportu: R-7K3Q9M')).toBeTruthy();
  } finally {
    process.off('unhandledRejection', onRejection);
    vi.unstubAllGlobals();
  }
});
