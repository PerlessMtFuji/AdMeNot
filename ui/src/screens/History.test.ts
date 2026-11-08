import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { groupHistory } from '../lib/logic';
import type { HistoryAction, HistoryView, UndoDone } from '../lib/types';
import { Controller } from '../lib/controller';
import { createFakeBridge } from '../lib/fakeBridge';
import { AppState } from '../lib/state.svelte';
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
      status_label: 'w toku', client: null, model: 'SM-A145R', interrupted: true, manual: false, screenshots: 0,
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

test('history: apps named and pictured from the order snapshot, package below the name, without a scan', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = view({ interrupted: false, status: 'done', status_label: 'wykonane',
    apps: { p: { name: 'Pogoda Live', icon: 'data:image/png;base64,AA==' } } });
  s.screen = 'history';
  await tick();
  const card = screen.getByRole('article', { name: 'ZS/2026/0926/05' });
  expect(within(card).getByText('Pogoda Live')).toBeTruthy();
  expect(within(card).getByText('p').className).toContain('text-2xs');
  expect(card.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,AA==');
});

test('history: report button next to each order', async () => {
  const { s, ctl, bridge } = await setupCtl('report');
  render(App, { props: { ctl } });
  await ctl.startScan();
  await vi.waitFor(() => expect(s.job).toBeNull());
  await fireEvent.click(screen.getByRole('button', { name: /Podsumowanie/ }));
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

test('history: deleting an order asks first, then calls the bridge', async () => {
  const { s, bridge } = await openHistory();
  const order = s.history!.orders[0];
  const card = screen.getByRole('article', { name: order.number });
  await fireEvent.click(within(card).getByRole('button', { name: 'Usuń zlecenie' }));
  const dialog = screen.getByRole('dialog', { name: `Usunąć zlecenie ${order.number}?` });
  expect(bridge.calls.some((c) => c.method === 'delete_order')).toBe(false);
  await fireEvent.click(within(dialog).getByRole('button', { name: 'Usuń' }));
  await vi.waitFor(() =>
    expect(bridge.calls.some((c) => c.method === 'delete_order' && c.args[0] === order.number)).toBe(true));
});

test('history: an order made in manual mode is tagged', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = view({ interrupted: false, status: 'done', status_label: 'wykonane' });
  s.screen = 'history';
  await tick();
  expect(within(screen.getByRole('article', { name: 'ZS/2026/0926/05' })).queryByText('tryb ręczny')).toBeNull();
  s.history = view({ interrupted: false, status: 'done', status_label: 'wykonane', manual: true });
  await tick();
  expect(within(screen.getByRole('article', { name: 'ZS/2026/0926/05' })).getByText('tryb ręczny')).toBeTruthy();
});

test('history: a channel fix cannot be undone from here and says where to turn it back on', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  const manual = 'Na telefonie: Chrome → Ustawienia → Powiadomienia → tanie-bilety.example';
  s.history = view({ interrupted: false, status: 'done', status_label: 'wykonane', actions: [
    { id: 4, package: 'com.android.chrome', level: 'fix', level_label: 'Ustawienia witryn', kind: 'channel',
      step_label: 'Wyłączenie powiadomień: tanie-bilety.example (Chrome)', status: 'done', status_label: 'wykonane',
      error: null, manual_undo: manual }] });
  s.screen = 'history';
  await tick();
  const card = screen.getByRole('article', { name: 'ZS/2026/0926/05' });
  expect(card.textContent).toContain('Zmieniono ustawienia witryn w 1 przeglądarce');
  expect(within(card).queryByRole('button', { name: /^Przywróć/ })).toBeNull();
  await fireEvent.click(within(card).getByRole('button', { name: 'Kroki' }));
  expect(within(card).getByText(manual)).toBeTruthy();
  expect(within(card).queryByRole('button', { name: /Przywróć/ })).toBeNull();
});

test('history: an order with only a channel fix left offers no undo of the whole order', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.history = view({ interrupted: false, status: 'partially_undone', status_label: 'częściowo cofnięte', actions: [
    { id: 4, package: 'com.android.chrome', level: 'fix', level_label: 'Ustawienia witryn', kind: 'channel',
      step_label: 'Wyłączenie powiadomień: tanie-bilety.example (Chrome)', status: 'done', status_label: 'wykonane',
      error: null, manual_undo: 'Na telefonie: Chrome → Ustawienia → Powiadomienia' }] });
  s.screen = 'history';
  await tick();
  const card = screen.getByRole('article', { name: 'ZS/2026/0926/05' });
  expect(within(card).queryByRole('button', { name: 'Cofnij całe zlecenie' })).toBeNull();
});

const ORDER = 'ZS/2026/0926/05';
const CHROME = 'com.android.chrome';

function channel(id: number, over: Partial<HistoryAction> = {}): HistoryAction {
  return { id, package: CHROME, level: 'fix', level_label: 'Ustawienia witryn', kind: 'channel',
    step_label: `Wyłączenie powiadomień: s${id}.example (Chrome)`, status: 'done', status_label: 'wykonane',
    error: null, manual_undo: null, site_url: null, ...over };
}

async function channelHistory(actions: HistoryAction[]) {
  const env = await setupCtl('empty');
  render(App, { props: { ctl: env.ctl } });
  env.s.history = view({ interrupted: false, status: 'done', status_label: 'wykonane', actions });
  env.s.screen = 'history';
  await tick();
  const card = screen.getByRole('article', { name: ORDER });
  await fireEvent.click(within(card).getByRole('button', { name: 'Kroki' }));
  return { ...env, card };
}

function undoDone(over: Partial<UndoDone> = {}): UndoDone {
  return { order: ORDER, status: 'undone', status_label: 'cofnięte', errors: [], admin_not_restored: false,
    sites_total: 0, sites_restored: 0, restored_sites: [], firefox_debugging: false, interrupted: [], ...over };
}

test('channel step done shows enable-on-phone button that undoes only that step', async () => {
  const { bridge, card } = await channelHistory([channel(4)]);
  expect(within(card).getAllByRole('button', { name: /^Przywróć/ })).toHaveLength(1); // cała przeglądarka też
  await fireEvent.click(within(card).getByRole('button', { name: '📱 Włącz na telefonie' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'undo', args: [ORDER, 4, null] });
});

test('browser row without a saved icon shows the built-in logo', async () => {
  const { card } = await channelHistory([channel(4)]);
  expect(card.querySelector('img[data-app-icon]')?.getAttribute('src')).toMatch(/chrome/);
});

test('gone channel shows the manual path instead of the button', async () => {
  const manual = 'Na telefonie: Chrome → Ustawienia → Powiadomienia → s4.example';
  const { card } = await channelHistory([channel(4, { error: 'kanał zniknął', manual_undo: manual })]);
  expect(within(card).getByText(manual)).toBeTruthy();
  expect(within(card).queryByRole('button', { name: '📱 Włącz na telefonie' })).toBeNull();
});

test('undone channel step shows open-site button', async () => {
  const { bridge, card } = await channelHistory([
    channel(4, { status: 'undone', status_label: 'cofnięte', site_url: 'https://s4.example' }),
    channel(5, { status: 'undone', status_label: 'cofnięte' })]);
  const buttons = within(card).getAllByRole('button', { name: '🌐 Otwórz stronę na telefonie' });
  expect(buttons).toHaveLength(1);
  await fireEvent.click(buttons[0]);
  expect(bridge.calls.at(-1)).toEqual({ method: 'open_site', args: [ORDER, 4] });
});

test('open-site buttons wait for any running job, not only orders', async () => {
  const { s } = await channelHistory([
    channel(4, { status: 'undone', status_label: 'cofnięte', site_url: 'https://s4.example' })]);
  s.undoResult = undoDone({ sites_total: 1, sites_restored: 1, restored_sites: [
    { action_id: 4, package: CHROME, browser: 'Chrome', site: 's4.example', url: 'https://s4.example' }] });
  s.job = { id: 'job-scan', kind: 'scan' }; // telefon zajęty zadaniem, które nie jest zleceniem
  await tick();
  const step = screen.getByRole('button', { name: '🌐 Otwórz stronę na telefonie' }) as HTMLButtonElement;
  const banner = screen.getByRole('button', { name: '🌐 Chrome · s4.example' }) as HTMLButtonElement;
  expect([step.disabled, banner.disabled]).toEqual([true, true]);
  s.job = null;
  await tick();
  expect([step.disabled, banner.disabled]).toEqual([false, false]);
});

test('undo of an app from the results goes to history when sites need the phone', async () => {
  const fake = createFakeBridge('empty', { delay: 0 });
  // nagrane scenariusze nie mają cofania z witrynami: `undo` tylko zwraca zadanie, zdarzenia wysyła test
  const api = new Proxy(fake.api, { get: (target, method: string) =>
    method === 'undo' ? async () => ({ job_id: 'job-u' }) : (target as unknown as Record<string, unknown>)[method] });
  const ctl = new Controller(new AppState(), { ...fake, api });
  await ctl.init();
  render(App, { props: { ctl } });
  const s = ctl.state;
  s.actedLog = { [CHROME]: [{ order: ORDER, level: 'disable' }] };
  await ctl.undoApp(CHROME);
  expect(s.job).toEqual({ id: 'job-u', kind: 'undo' });
  expect(s.screen).toBe('main');
  fake.emit('undo:sites', { order: ORDER, sites: [{ action_id: 4, package: CHROME, browser: 'Chrome', site: 's4.example' }] });
  fake.emit('exec:user_wait', { package: CHROME, name: 'Chrome', kind: 'channel', browser: 'Chrome', site: 's4.example',
    timeout: 180, action_id: 4 });
  await vi.waitFor(() => expect(s.screen).toBe('history'));
  await tick();
  expect(screen.getByText('Cofam zmiany…')).toBeTruthy();
  const queue = screen.getByRole('region', { name: 'Przywracanie powiadomień witryn' });
  expect(within(queue).getByRole('listitem').getAttribute('aria-current')).toBe('step');
  expect(queue.textContent).toContain('Chrome · s4.example');
});

test('open site failure shows a warning banner', async () => {
  const { s, bridge, card } = await channelHistory([
    channel(4, { status: 'undone', status_label: 'cofnięte', site_url: 'https://s4.example' })]);
  bridge.failNext('open_site', 'busy');
  await fireEvent.click(within(card).getByRole('button', { name: '🌐 Otwórz stronę na telefonie' }));
  await vi.waitFor(() => expect(screen.getByText('Nie udało się otworzyć strony na telefonie.')).toBeTruthy());
  expect(s.error).toBeNull(); // ostrzeżenie w banerze, nie karta błędu
});

test('undo of a whole order with sites lists the queue and expands the current site', async () => {
  const { s, bridge } = await channelHistory([channel(4), channel(5), channel(6)]);
  s.job = { id: 'job-9', kind: 'undo' };
  bridge.emit('undo:sites', { order: ORDER, sites: [
    { action_id: 4, package: CHROME, browser: 'Chrome', site: 's4.example' },
    { action_id: 5, package: CHROME, browser: 'Chrome', site: 's5.example' },
    { action_id: 6, package: 'com.sec.android.app.sbrowser', browser: 'Samsung Internet', site: null }] });
  bridge.emit('undo:step', { action_id: 4, package: CHROME, name: 'Chrome', kind: 'channel', label: '', status: 'undone',
    error: null, error_key: null });
  bridge.emit('exec:user_wait', { package: CHROME, name: 'Chrome', kind: 'channel', browser: 'Chrome', site: 's5.example',
    timeout: 180, action_id: 5 });
  await tick();
  const queue = screen.getByRole('region', { name: 'Przywracanie powiadomień witryn' });
  expect(queue.textContent).toContain('Włączaj kolejno przełączniki na telefonie — program sam przejdzie dalej.');
  const items = within(queue).getAllByRole('listitem');
  expect(items.map((li) => li.getAttribute('aria-current'))).toEqual([null, 'step', null]);
  expect(items[0].textContent).toContain('Chrome · s4.example');
  expect(items[0].textContent).toContain('włączona');
  expect(items.map((li) => li.querySelector('img[data-app-icon]')?.getAttribute('src'))).toEqual([
    expect.stringMatching(/chrome/), expect.stringMatching(/chrome/), expect.stringMatching(/samsung/)]);
  expect(items[1].textContent).toContain('Chrome · s5.example');
  expect(items[1].textContent).toContain('Włącz „Pokazuj powiadomienia”.');
  expect(items[1].textContent).toContain('3:00');
  expect(items[2].textContent).toContain('Samsung Internet · wszystkie witryny');
  expect(items[2].textContent).toContain('czeka');
  await fireEvent.click(within(items[1]).getByRole('button', { name: 'Otwórz ponownie na telefonie' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'reopen_screen', args: [] });
});

test('undo banner counts restored sites', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.screen = 'history';
  s.undoResult = undoDone({ status: 'partially_undone', status_label: 'częściowo cofnięte', sites_total: 3, sites_restored: 2 });
  await tick();
  expect(screen.getByText('Włączono 2 z 3 witryn.')).toBeTruthy();
  expect(screen.getByText('Pozostałe włączysz z historii zlecenia.')).toBeTruthy();
  expect(screen.queryByText('Wyłącz w Firefoxie zdalne debugowanie przez USB')).toBeNull();
  s.undoResult = undoDone({ sites_total: 1, sites_restored: 1, firefox_debugging: true });
  await tick();
  expect(screen.getByText('Włączono 1 z 1 witryny.')).toBeTruthy();
  expect(screen.queryByText('Pozostałe włączysz z historii zlecenia.')).toBeNull();
  expect(screen.getByText('Wyłącz w Firefoxie zdalne debugowanie przez USB')).toBeTruthy();
  s.undoResult = undoDone();
  await tick();
  expect(screen.queryByText(/Włączono/)).toBeNull();
});

test('undo banner lists restored sites with open buttons', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.screen = 'history';
  s.undoResult = undoDone({ sites_total: 2, sites_restored: 2, restored_sites: [
    { action_id: 4, package: CHROME, browser: 'Chrome', site: 's4.example', url: 'https://s4.example' },
    { action_id: 5, package: CHROME, browser: 'Chrome', site: 's5.example', url: null }] });
  await tick();
  expect(screen.getByText(/strona musi zapisać telefon od nowa/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: '🌐 Chrome · s5.example' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: '🌐 Chrome · s4.example' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'open_site', args: [ORDER, 4] });
  s.undoResult = undoDone({ sites_total: 1, sites_restored: 1, restored_sites: [
    { action_id: 5, package: CHROME, browser: 'Chrome', site: 's5.example', url: null }] });
  await tick();
  expect(screen.queryByText(/strona musi zapisać telefon od nowa/)).toBeNull();
});

const TRANSFER = { number: 'ZS/2026/1025/02', client: 'Anna K.', created_at: '2026-10-25T14:20:00',
  source: { name: 'Samsung A52', imei: '351111111111111' }, target: { name: 'OPPO A54', imei: '862222222222222' },
  state: 'restored' as const, notes: 0, copy: { id: 'OLD/1', days_left: 6, deleted_at: null }, whatsapp_restored: false,
  apps_blocked: false, counts: { contacts: 5 } };

test('transfers of all phones sit on their own tab, without the phone panel of the repair history', async () => {
  const env = await setupCtl('adware');
  env.bridge.setOrders([TRANSFER]);
  render(App, { props: { ctl: env.ctl } });
  await env.ctl.openHistory();
  await vi.waitFor(() => expect(env.s.transfer.orders).toHaveLength(1));
  await tick();
  const tabs = screen.getByRole('group', { name: 'Widok historii' });
  expect(within(tabs).getByRole('button', { name: 'Naprawy' }).getAttribute('aria-pressed')).toBe('true');
  expect(screen.queryByRole('article', { name: /Samsung A52/ })).toBeNull();
  expect(screen.getByRole('complementary', { name: 'Telefon' })).toBeTruthy();
  await fireEvent.click(within(tabs).getByRole('button', { name: 'Przeniesienia (1)' }));
  expect(screen.getByRole('article', { name: /Samsung A52 → OPPO A54/ })).toBeTruthy();
  expect(screen.queryByRole('complementary', { name: 'Telefon' })).toBeNull();
  // „Wgraj kopię” i „Inna kopia” z ekranu Połącz otwierają od razu zakładkę przeniesień
  await fireEvent.click(within(tabs).getByRole('button', { name: 'Naprawy' }));
  env.s.screen = 'main';
  await env.ctl.openHistory(null, 'transfers');
  await tick();
  expect(screen.getByRole('article', { name: /Samsung A52 → OPPO A54/ })).toBeTruthy();
});

test('the transfers tab counts orders and copies without an order, and the repair tab shows no transfers', async () => {
  const env = await setupCtl('adware');
  env.bridge.setOrders([TRANSFER]);
  env.bridge.setCopies([{ id: 'OLD/7', serial: 'S7', model: 'Moto G54', manufacturer: 'motorola', client: null,
    created: '2026-10-20T12:00:00', expires: '2026-10-27T12:00:00', days_left: 2, status: 'in_progress', bytes: 1, counts: {},
    order: null, restores: [] }]);
  render(App, { props: { ctl: env.ctl } });
  await env.ctl.openHistory();
  await vi.waitFor(() => expect(env.s.transfer.orders).toHaveLength(1));
  await tick();
  const tabs = screen.getByRole('group', { name: 'Widok historii' });
  expect(within(tabs).getByRole('button', { name: 'Przeniesienia (2)' })).toBeTruthy();
  expect(screen.queryByText(TRANSFER.number)).toBeNull();  // zakładka „Naprawy” bez przeniesień
});

test('without transfers the history has no tabs', async () => {
  const { s } = await openHistory();
  expect(s.transfer.orders).toEqual([]);
  expect(screen.queryByRole('group', { name: 'Widok historii' })).toBeNull();
});
