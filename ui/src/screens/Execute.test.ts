import { fireEvent, render, screen, within } from '@testing-library/svelte';
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
  test('report button opens the PDF, then shows the PDF error', async () => {
    const { s, bridge } = await scanned('report');
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    await fireEvent.click(await screen.findByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    const rail = screen.getByRole('list', { name: 'Etapy' });
    expect(rail.children[4].getAttribute('aria-current')).toBe('step');
    const button = screen.getByRole('button', { name: 'Protokół PDF' });
    await fireEvent.click(button);
    expect(await screen.findByText(/Otwarto protokół/)).toBeTruthy();
    expect(bridge.calls.filter((c) => c.method === 'report')).toEqual([
      { method: 'report', args: [s.result!.order] }]);
    expect(rail.children[4].getAttribute('aria-current')).toBeNull(); // etap 5 zrobiony
    await fireEvent.click(button);
    expect(await screen.findByText(/otwarty w innym programie/)).toBeTruthy();
  });

  test('preview, run, results, new scan', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    const confirm = await screen.findByRole('region', { name: 'Plan naprawy' });
    expect(confirm.textContent).toContain('wyłączenie aplikacji');
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    expect(screen.getByRole('heading', { name: 'Telefon naprawiony' })).toBeTruthy();
    expect(screen.getAllByText(/· sprawdzone$/)).toHaveLength(s.result!.apps.length);
    await fireEvent.click(screen.getByRole('button', { name: 'Nowe skanowanie' }));
    expect(s.phase).toBe('connect');
  });

  test('back to repair: same results, done apps marked, a removed app cannot be picked again', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    await fireEvent.click(await screen.findByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Wróć do naprawy' }));
    await tick();
    expect(s.phase).toBe('results');
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    const card = screen.getByRole('article', { name: boost.name });
    expect(card.textContent).toContain('usunięta');
    expect((card.querySelector('input[type="checkbox"]') as HTMLInputElement).disabled).toBe(true);
  });

  test('back to repair, then undo one app right from its card', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    await fireEvent.click(await screen.findByRole('button', { name: /^Wykonaj/ }));
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Wróć do naprawy' }));
    await vi.waitFor(() => expect(s.job).toBeNull());
    await tick();
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    const card = screen.getByRole('article', { name: boost.name });
    await fireEvent.click(within(card).getByRole('button', { name: `Cofnij: ${boost.name}` }));
    await vi.waitFor(() => expect(s.job).toBeNull());
    await tick();
    expect(s.phase).toBe('results');
    expect(card.textContent).not.toContain('usunięta');
    expect((card.querySelector('input[type="checkbox"]') as HTMLInputElement).disabled).toBe(false);
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

  test('back from the confirmation returns to the plan panel', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: /Napraw zaznaczone/ }));
    await screen.findByRole('region', { name: 'Plan naprawy' });
    await fireEvent.click(screen.getByRole('button', { name: 'Wróć' }));
    expect(s.plan).toBeNull();
    expect(screen.getByRole('button', { name: /Napraw zaznaczone/ })).toBeTruthy();
    expect(screen.getByRole('main').hasAttribute('inert')).toBe(false);
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
    expect(screen.getByText('Dezaktywuj')).toBeTruthy();
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
    const card = screen.getByRole('article', { name: 'Druga' });
    expect(card.textContent).toContain('Wstrzymana');
    expect(card.textContent).toContain('Wyłącz');
    expect(screen.getAllByText('Wstrzymana')).toHaveLength(2);
  });

  test('stopped order offers to finish it', async () => {
    const { s, bridge } = await app('empty');
    s.phase = 'executing';
    bridge.emit('exec:done', { order: 'ZS/2026/0926/02', status: 'running', status_label: 'w toku',
      stopped: true, apps: [{ package: 'p', name: 'P', outcome: 'stopped', errors: [], kinds: [] }] });
    await tick();
    expect(screen.getByRole('heading', { name: 'Zlecenie wstrzymane' })).toBeTruthy();
    expect(screen.getByText('Wstrzymana')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Dokończ' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'resume', args: ['ZS/2026/0926/02'] });
  });

  test('progress counts finished steps of the plan', async () => {
    const { bridge } = await app('empty');
    const plan = { package: 'a', name: 'Pierwsza', level: 'disable' as const, level_label: 'WYŁĄCZ', blocked: false,
      reason: null, reason_text: null, steps: ['x', 'y', 'z', 'w'], warnings: [] };
    bridge.emit('exec:order', { order: 'ZS/2026/0926/06', plan: { runnable: 1, apps: [plan] } });
    bridge.emit('exec:step', { action_id: 1, package: 'a', name: 'Pierwsza', kind: 'x', label: 'x', status: 'done', error: null });
    bridge.emit('exec:step', { action_id: 2, package: 'a', name: 'Pierwsza', kind: 'y', label: 'y', status: 'running', error: null });
    await tick();
    expect(screen.getByRole('heading', { name: 'Naprawiam telefon…' })).toBeTruthy();
    expect(screen.getByText('krok 2 z 4')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('25');
  });
});
