import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { setupCtl } from '../test-utils';

async function app(scenario: string) {
  const env = await setupCtl(scenario);
  render(App, { props: { ctl: env.ctl } });
  return env;
}

async function scanned(scenario = 'adware') {
  const env = await app(scenario);
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  await tick();
  return env;
}

describe('plan and execution', () => {
  test('preview, run, results, new scan', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Plan naprawy' });
    expect(dialog.textContent).toContain('wyłączenie aplikacji');
    await fireEvent.click(screen.getByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getAllByText('✓ Gotowe')).toHaveLength(s.result!.apps.length);
    expect(screen.getByText(new RegExp(`${s.result!.order}: wykonane`))).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Nowe skanowanie' }));
    expect(s.phase).toBe('connect');
  });

  test('undo from the result goes to history', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    await fireEvent.click(await screen.findByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Cofnij całe zlecenie' }));
    await vi.waitFor(() => expect(s.undoResult?.status).toBe('undone'));
    expect(s.screen).toBe('history');
  });

  test('blocked app can be unlocked in expert mode', async () => {
    const { s, ctl, bridge } = await scanned();
    await ctl.setMode('expert');
    s.plan = {
      runnable: 0,
      apps: [{ package: 'com.sec.android.app.launcher', name: 'Launcher', level: 'disable',
        level_label: 'WYŁĄCZ', blocked: true, reason: 'protected',
        reason_text: 'aplikacja chroniona', steps: [], warnings: [] }],
    };
    await tick();
    expect(screen.getByText(/Nic do wykonania/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /^Wykonaj/ }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: 'Odblokuj' }));
    expect(bridge.calls.at(-1)).toMatchObject({ method: 'preview_plan', args: [expect.anything(),
      ['com.sec.android.app.launcher']] });
  });

  test('admin prompt, question dialog and pause', async () => {
    const { s, bridge } = await app('empty');
    s.phase = 'executing';
    s.order = 'ZS/2026/0926/01';
    s.job = { id: 'job-4', kind: 'exec' };
    bridge.emit('exec:step', { action_id: 1, package: 'p', name: 'Cleaner', kind: 'enabled',
      label: 'wyłączenie aplikacji', status: 'running', error: null });
    bridge.emit('exec:admin_wait', { package: 'p', name: 'Cleaner', timeout: 180 });
    await tick();
    expect(screen.getByText('Potrzebny jeden ruch na telefonie')).toBeTruthy();
    expect(screen.getByText(/Stuknij „Dezaktywuj” przy Cleaner/)).toBeTruthy();
    expect(screen.getByText(/Czekam jeszcze 3:00|Czekam jeszcze 2:5\d/)).toBeTruthy();
    bridge.emit('exec:question', { job_id: 'job-4', kind: 'admin_timeout', package: 'p', name: 'Cleaner' });
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Pomiń' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'answer', args: ['job-4', 'skip'] });
    await fireEvent.click(screen.getByRole('button', { name: 'Wstrzymaj' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'stop', args: ['job-4'] });
    await tick();
    expect(screen.getByRole('button', { name: /Wstrzymuję/ })).toBeTruthy();
  });

  test('after a pause the apps never started stay listed in the result', async () => {
    const { s, bridge } = await app('empty');
    const plan = (pkg: string, name: string) => ({ package: pkg, name, level: 'disable' as const,
      level_label: 'WYŁĄCZ', blocked: false, reason: null, reason_text: null, steps: [], warnings: [] });
    bridge.emit('exec:order', { order: 'ZS/2026/0926/05', plan: { runnable: 2,
      apps: [plan('a', 'Pierwsza'), plan('b', 'Druga')] } });
    bridge.emit('exec:step', { action_id: 1, package: 'a', name: 'Pierwsza', kind: 'enabled',
      label: 'wyłączenie aplikacji', status: 'done', error: null });
    await tick();
    expect(screen.getByText(/Czeka w kolejce/)).toBeTruthy();
    bridge.emit('exec:done', { order: 'ZS/2026/0926/05', status: 'running', status_label: 'w toku',
      stopped: true, apps: [
        { package: 'a', name: 'Pierwsza', outcome: 'stopped', errors: [], kinds: [] },
        { package: 'b', name: 'Druga', outcome: 'stopped', errors: [], kinds: [] }] });
    await tick();
    expect(s.phase).toBe('done');
    expect(screen.queryByText(/Czeka w kolejce/)).toBeNull();
    const card = screen.getByText('Druga').closest('.card') as HTMLElement;
    expect(card.textContent).toContain('⏸ Wstrzymana');
    expect(card.textContent).toContain('WYŁĄCZ');
    expect(screen.getAllByText('⏸ Wstrzymana')).toHaveLength(2);
  });

  test('stopped order offers to finish it', async () => {
    const { s, bridge } = await app('empty');
    s.phase = 'executing';
    bridge.emit('exec:done', { order: 'ZS/2026/0926/02', status: 'running', status_label: 'w toku',
      stopped: true, apps: [{ package: 'p', name: 'P', outcome: 'stopped', errors: [], kinds: [] }] });
    await tick();
    expect(screen.getByText(/Zlecenie wstrzymane/)).toBeTruthy();
    expect(screen.getByText('⏸ Wstrzymana')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Dokończ' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'resume', args: ['ZS/2026/0926/02'] });
  });
});
