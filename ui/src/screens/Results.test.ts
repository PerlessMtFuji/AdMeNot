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

// Tylko wiersze tabeli aplikacji — panel szczegółów ma własną tabelę (możliwości aplikacji).
const appRows = () => within(screen.getByRole('group', { name: 'Tabela aplikacji' })).getAllByRole('row');

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
    expect(screen.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeTruthy();
    expect(screen.getByText(`W zakresie wykonanego skanu · sprawdzone aplikacje: ${s.scan!.counts.total}`)).toBeTruthy();
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
    expect(appRows()).toHaveLength(flagged.length + 1);
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
    expect(appRows()).toHaveLength(2);
    expect(within(panel).getByText('com.wlive.forecast')).toBeTruthy();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'zzz-nothing' } });
    expect(appRows()).toHaveLength(1);
    expect(within(panel).getByText('Wybierz aplikację w tabeli.')).toBeTruthy();
    await fireEvent.keyDown(table, { key: 'ArrowUp' });
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Akcja com.wlive.forecast' }),
      { target: { value: 'silence' } });
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await fireEvent.click(screen.getByRole('button', { name: `Wszystkie · ${s.scan!.apps.length}` }));
    expect(appRows()).toHaveLength(s.scan!.apps.length + 1);
  });
  test('expert filters: problem type chips and source list narrow the table, clear brings it back', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    const types = screen.getByRole('group', { name: 'Rodzaj problemu' });
    const ads = within(types).getByRole('button', { name: /^Reklamy/ });
    expect(ads.getAttribute('aria-pressed')).toBe('false');
    await fireEvent.click(ads);
    expect(ads.getAttribute('aria-pressed')).toBe('true');
    expect(appRows()).toHaveLength(2);
    expect(screen.getByRole('checkbox', { name: 'com.clean.pro.boost' })).toBeTruthy();
    const source = screen.getByRole('combobox', { name: 'Filtr źródła' });
    expect(within(source).getByRole('option', { name: 'Wszystkie źródła' })).toBeTruthy();
    await fireEvent.change(source, { target: { value: 'Sklep Play' } });
    expect(appRows()).toHaveLength(1);
    expect(screen.getByText('Brak aplikacji pasujących do filtrów.')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść filtry' }));
    expect(appRows()).toHaveLength(flagged.length + 1);
    expect(s.categoryFilter).toEqual([]);
    expect(s.sourceFilter).toBeNull();
    await fireEvent.change(source, { target: { value: 'Chrome' } });
    ctl.newScan();
    expect(s.sourceFilter).toBeNull();
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

describe('Results: missing data is never a plain "all clear" (final review I2/M2)', () => {
  const GAP = { key: 'device_policy', label: 'administratorzy urządzenia' };

  // Linia uwag: krótki tekst widoczny od razu, pełne komunikaty dopiero po „Więcej”.
  const notesLine = () => screen.getByRole('status', { name: 'Uwagi do skanu' });
  async function openNotes() {
    const line = notesLine();
    if (line.querySelector('[aria-expanded="false"]')) await fireEvent.click(within(line).getByRole('button', { name: 'Więcej' }));
  }

  function devicePolicyFailed(s: Awaited<ReturnType<typeof scanned>>['s']) {
    const scan = s.scan!;
    s.scan = {
      ...scan,
      collectors: { ...scan.collectors, ok: scan.collectors.total - 1,
        failed: [{ name: 'device_policy', error: 'timeout' }] },
      apps: scan.apps.map((a) => ({ ...a, incomplete: true, gaps: [GAP],
        verdict_label: a.verdict === 'safe' ? 'Brak istotnych sygnałów (ocena niepełna)' : a.verdict_label })),
    };
  }

  test('clean phone with a failed collector: warn banner, scoped title, incomplete pills', async () => {
    const { s } = await scanned('clean');
    devicePolicyFailed(s);
    await tick();
    const n = s.scan!.apps.length;
    expect(screen.queryByRole('heading', { name: t('results.clean_title') })).toBeNull();
    expect(screen.getByRole('heading', { name: t('results.clean_title_incomplete') })).toBeTruthy();
    expect(notesLine().textContent).toContain(t('notice.short.incomplete', { count: n }));
    await openNotes();
    expect(screen.getByText(t('summary.incomplete', { count: n, names: GAP.label }))).toBeTruthy();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    const toggle = within(panel).getByRole('button', { name: new RegExp(tp('results.safe_incomplete', n)) });
    await fireEvent.click(toggle);
    const list = screen.getByRole('list', { name: t('results.safe_list') });
    expect(within(list).getAllByText(t('results.incomplete'))).toHaveLength(n);
  });

  test('a failed or partial collector alone still shows the warn banner', async () => {
    const { s } = await scanned('clean');
    s.scan = { ...s.scan!, collectors: { ...s.scan!.collectors,
      partial: [{ name: 'appops', count: 1 }] } };
    await tick();
    expect(notesLine().textContent).toContain(t('notice.short.incomplete', { count: 0 }));
    await openNotes();
    expect(screen.getByText(t('summary.incomplete', { count: 0, names: 'appops' }))).toBeTruthy();
  });

  test('unknown profile list gets its own banner; a known single profile does not', async () => {
    const { s } = await scanned('clean');
    s.scan = { ...s.scan!, profiles: { others: [], known: false } };
    await tick();
    expect(notesLine().textContent).toContain(t('notice.short.profiles_unknown'));
    await openNotes();
    expect(screen.getByText(t('summary.profiles_unknown'))).toBeTruthy();
    s.scan = { ...s.scan!, profiles: { others: [], known: true } };
    await tick();
    expect(screen.queryByRole('status', { name: 'Uwagi do skanu' })).toBeNull();
    expect(screen.queryByText(t('summary.profiles_unknown'))).toBeNull();
  });

  test('Android 12 and older: notifications only by hand; default action silence becomes disable', async () => {
    const { s } = await scanned('clean');
    expect(screen.queryByText(t('summary.notifications_manual'))).toBeNull();
    s.device = { ...s.device!, sdk: 31 };
    await tick();
    expect(notesLine().textContent).toContain(t('notice.short.notifications_manual'));
    await openNotes();
    expect(screen.getByText(t('summary.notifications_manual'))).toBeTruthy();
    expect(screen.getByText(t('summary.select_level_disable'))).toBeTruthy();
    s.settings = { ...s.settings, select_level: 'remove' };
    await tick();
    expect(screen.queryByText(t('summary.select_level_disable'))).toBeNull();
  });

  test('a failed undo of one app is explained on the results list', async () => {
    const { s } = await scanned('clean');
    const app = s.scan!.apps[0];
    s.undoTarget = app.package;
    s.undoResult = { order: 'ZS', status: 'partially_undone', status_label: '', errors: ['Brak kopii aplikacji.'], admin_not_restored: false };
    await tick();
    expect(screen.getByText(t('summary.undo_app_failed', { name: app.name }))).toBeTruthy();
    expect(screen.getByText('Brak kopii aplikacji.')).toBeTruthy();
  });

  test('low-data banner shows the hours; other profiles banner lists their ids', async () => {
    const { s } = await scanned();
    s.scan = { ...s.scan!, low_behavior_data: true, usage_window_h: 1.5,
      profiles: { others: [10, 11], known: true } };
    await tick();
    expect(notesLine().textContent).toContain(t('notice.short.low_data', { hours: '1.5' }));
    await openNotes();
    expect(screen.getByText(t('summary.low_data', { hours: '1.5' }))).toBeTruthy();
    expect(t('summary.low_data', { hours: '1.5' })).toContain('1.5 h');
    expect(screen.getByText(t('summary.profiles', { ids: '10, 11' }))).toBeTruthy();
  });

  test('APK estimate, space question and no-space stop', async () => {
    const { s, bridge } = await scanned();
    const GB = 1024 ** 3;
    s.apk = { ...s.apk, running: true };
    bridge.emit('apk:estimate', { to_fetch_bytes: 7.2 * GB, total_bytes: 7.2 * GB, apps: 142, unknown: 3, cached: 0,
      largest_bytes: 3 * GB, limit_bytes: 10 * GB, effective_bytes: 2 * GB, free_bytes: 4 * GB });
    expect(await screen.findByText(/Analiza pobierze ok. 7,2 GB \(142 aplikacje\)/)).toBeTruthy();
    expect(screen.getByText(/Na dysku jest miejsce na 2,0 GB/)).toBeTruthy();
    expect(tp('apk_cache.estimate', 5, { size: '1,0 GB' })).toBe('Analiza pobierze ok. 1,0 GB (5 aplikacji)');
    bridge.emit('apk:question', { job_id: 'job-9', kind: 'no_space', to_fetch_bytes: 7.2 * GB, total_bytes: 7.2 * GB,
      apps: 142, unknown: 0, cached: 0, largest_bytes: 3 * GB, limit_bytes: 10 * GB, effective_bytes: 2 * GB, free_bytes: 4 * GB });
    await fireEvent.click(await screen.findByRole('button', { name: 'Wyczyść i analizuj' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'answer', args: ['job-9', 'clear'] });
    const stopped = { ...JSON.parse(JSON.stringify(s.scan)), apk: { requested: 142, analyzed: 61, failed: {}, stopped_no_space: true } };
    bridge.emit('apk:done', { scan: stopped });
    expect(await screen.findByText('Zabrakło miejsca na dysku. Przeanalizowano 61 ze 142 aplikacji.')).toBeTruthy();
  });

  test('APK estimate says what is already on the computer', async () => {
    const { s, bridge } = await scanned();
    const GB = 1024 ** 3;
    const base = { total_bytes: 5 * GB, unknown: 0, largest_bytes: 0, limit_bytes: 10 * GB,
      effective_bytes: 10 * GB, free_bytes: 50 * GB };
    s.apk = { ...s.apk, running: true };
    bridge.emit('apk:estimate', { ...base, to_fetch_bytes: 0, apps: 89, cached: 89 });
    expect(await screen.findByText(
      'Pliki wszystkich aplikacji do analizy (89) są już na komputerze — nic nie trzeba pobierać.')).toBeTruthy();
    bridge.emit('apk:estimate', { ...base, to_fetch_bytes: 30 * 1024 ** 2, apps: 89, cached: 87 });
    expect(await screen.findByText(
      'Analiza pobierze ok. 30 MB (2 z 89 aplikacji, pozostałe są już na komputerze).')).toBeTruthy();
  });
});
