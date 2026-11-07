import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import type { TaskView } from '../../lib/types';
import { setupCtl } from '../../test-utils';
import TaskBar from './TaskBar.svelte';

const SERIAL = 'R58T00TEST';
const DEST = 'D:\\Serwis\\Kowalska';

function task(over: Partial<TaskView> = {}): TaskView {
  return { id: 's1t1', kind: 'to_pc', status: 'running', done_files: 3, total_files: 10, done_bytes: 3 * 1024 * 1024,
    total_bytes: 10 * 1024 * 1024, speed: 2 * 1024 * 1024, eta_s: 150, skipped: 0, renamed: 0, failed: [], verified: null,
    dest: DEST, omitted: 0, targets: [], ...over };
}

async function setup() {
  const env = await setupCtl('explorer');
  const ex = env.ctl.explorer;
  await ex.open(SERIAL);
  render(TaskBar, { props: { ex } });
  const emit = async (t: TaskView) => {
    env.bridge.emit('explorer:task', { task: t });
    await tick();
  };
  return { ...env, ex, emit };
}

const calls = (bridge: { calls: { method: string; args: unknown[] }[] }, method: string) =>
  bridge.calls.filter((c) => c.method === method).map((c) => c.args);

describe('TaskBar', () => {
  test('unreadable items are reported as a problem, not as identical files', async () => {
    const { emit } = await setup();
    await emit(task({ status: 'done', omitted: 2, done_files: 0, total_files: 0, dest: '' }));
    expect(screen.getByText(/2 pozycje nieodczytane/)).toBeTruthy();
    expect(screen.getByText('Gotowe z błędami')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Otwórz folder' })).toBeNull();  // nic nie powstało
  });

  test('damaged files can be sent again', async () => {
    const { emit, ex, bridge } = await setup();
    await emit(task({ status: 'done', verified: 'mismatch', failed: [{ path: '/sdcard/a.jpg', reason: 'mismatch' }] }));
    await fireEvent.click(screen.getByRole('button', { name: 'Ponów uszkodzone' }));
    await vi.waitFor(() => expect(calls(bridge, 'explorer_retry')).toEqual([['s1t1']]));
    expect(ex.state.tasks.some((x) => x.id === 's1t1')).toBe(false);
  });

  test('a running copy shows progress, file count, speed and time left', async () => {
    const { emit } = await setup();
    await emit(task());
    expect(screen.getByText('Kopiowanie na komputer')).toBeTruthy();
    expect(screen.getByText('3 z 10')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('30');
    expect(screen.getByText(/2 MB\/s/)).toBeTruthy();
    expect(screen.getByText(/~3 min/)).toBeTruthy();
  });

  test('waiting for the phone is a Banner without a manual retry', async () => {
    const { emit } = await setup();
    await emit(task({ status: 'waiting' }));
    expect(screen.getByRole('status').textContent).toContain('Czeka na telefon — podłącz kabel, ruszy samo');
    expect(screen.queryByRole('button', { name: /Ponów|Spróbuj/ })).toBeNull();
  });

  test('pause, resume and cancel call the bridge with the task id', async () => {
    const { bridge, emit } = await setup();
    await emit(task());
    await fireEvent.click(screen.getByRole('button', { name: 'Wstrzymaj' }));
    expect(calls(bridge, 'explorer_pause')).toEqual([['s1t1']]);
    await emit(task({ status: 'paused' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Wznów' }));
    expect(calls(bridge, 'explorer_resume')).toEqual([['s1t1']]);
    await fireEvent.click(screen.getByRole('button', { name: 'Anuluj' }));
    expect(calls(bridge, 'explorer_cancel')).toEqual([['s1t1']]);
  });

  test('the queue unfolds with every task and its own controls', async () => {
    const { bridge, emit } = await setup();
    await emit(task());
    await emit(task({ id: 's1t2', kind: 'to_phone', status: 'queued', done_files: 0, dest: '/sdcard/Download' }));
    expect(screen.queryByText('W kolejce')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Kolejka zadań (2)' }));
    expect(screen.getByText('W kolejce')).toBeTruthy();
    const cancels = screen.getAllByRole('button', { name: 'Anuluj' });
    await fireEvent.click(cancels[cancels.length - 1]);
    expect(calls(bridge, 'explorer_cancel')).toEqual([['s1t2']]);
  });

  test('done with errors is not plain success: count, reasons, skipped and saved alongside', async () => {
    const { bridge, emit } = await setup();
    await emit(task({ status: 'done', done_files: 7, skipped: 2, renamed: 1, verified: 'size',
      failed: [{ path: '/sdcard/DCIM/a.jpg', reason: 'denied' }] }));
    expect(screen.getByText('Gotowe z błędami')).toBeTruthy();
    expect(screen.getByText(/1 pliku nie udało się skopiować/)).toBeTruthy();
    expect(screen.getByText(/2 identyczne pominięte/)).toBeTruthy();
    expect(screen.getByText(/1 zapisany obok/)).toBeTruthy();
    expect(screen.getByText(/a\.jpg — telefon nie pozwolił odczytać pliku/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Otwórz folder' }));
    expect(calls(bridge, 'explorer_open_folder')).toEqual([[DEST]]);
  });

  test('a finished upload offers "Show", which opens its phone folder', async () => {
    const { bridge, emit } = await setup();
    await emit(task({ kind: 'to_phone', status: 'done', done_files: 10, dest: '/sdcard/Download' }));
    expect(screen.getByText('Wgrano 10 plików')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Pokaż' }));
    await vi.waitFor(() => expect(calls(bridge, 'explorer_list').at(-1)).toEqual(['/sdcard/Download']));
  });

  test('a damaged copy is marked as damaged', async () => {
    const { emit } = await setup();
    await emit(task({ status: 'done', done_files: 9, verified: 'mismatch',
      failed: [{ path: '/sdcard/DCIM/Camera/2026/IMG_1.jpg', reason: 'mismatch' }] }));
    expect(screen.getByText(/1 uszkodzony/)).toBeTruthy();
    expect(screen.getByText(/IMG_1\.jpg — kopia uszkodzona/)).toBeTruthy();
  });

  test('a finished task can be dismissed', async () => {
    const { emit } = await setup();
    await emit(task({ status: 'cancelled' }));
    expect(screen.getByText('Anulowano')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Ukryj' }));
    expect(screen.queryByText('Anulowano')).toBeNull();
  });
});
