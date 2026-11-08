import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { flushSync, tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { CHECKS_SAMPLE } from '../lib/fakeBridge';
import type { CheckBrowser, DeviceCheck } from '../lib/types';
import { t, tp } from '../lib/i18n/index.svelte';
import { setupCtl } from '../test-utils';
import Results from './Results.svelte';

async function scanned(scenario = 'adware', checks?: DeviceCheck[]) {
  const env = await setupCtl(scenario, checks ? { checks } : {});
  render(App, { props: { ctl: env.ctl } });
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  await tick();
  return env;
}

// Tylko wiersze tabeli aplikacji — panel szczegółów ma własną tabelę (możliwości aplikacji).
const appRows = () => within(screen.getByRole('group', { name: 'Tabela aplikacji' })).getAllByRole('row');
const tab = (name: 'Aplikacje' | 'Telefon') => screen.getByRole('tab', { name: new RegExp(`^${name}`) });
const openPhone = () => fireEvent.click(tab('Telefon'));
// Dymek linii analizy: zdanie uspokajające i szacunek pobierania (spec §3 p.2) — czytany z nazwy ikony.
const apkHint = () => screen.getByRole('img', { name: /Na razie bez oznak|Analiza pobierze|Pliki wszystkich/ }).getAttribute('aria-label') ?? '';

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
    const tiles = within(within(card).getByTestId('reasons')).getAllByRole('img');
    expect(tiles.map((x) => x.getAttribute('aria-label'))).toEqual(boost.symptoms.map((sy) => t(`category.${sy.category}`)));
    await fireEvent.click(within(card).getByRole('button', { name: 'Dlaczego?' }));
    expect(within(card).getByText(boost.symptoms[0].text)).toBeTruthy();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    const count = Object.keys(s.selection).length;
    expect(within(panel).getByRole('button', { name: `Podsumowanie (${count})` })).toBeTruthy();
    expect(within(panel).getByText(boost.name)).toBeTruthy();
    await fireEvent.click(within(card).getByRole('button', { name: 'Wyłącz' }));
    expect(s.selection[boost.package]).toBe('disable');
    await fireEvent.click(within(card).getByRole('checkbox', { name: boost.name }));
    expect(s.selection[boost.package]).toBeUndefined();
    expect(within(panel).getByRole('button', { name: `Podsumowanie (${count - 1})` })).toBeTruthy();
    expect(within(panel).getByText('R58T00TEST')).toBeTruthy();
    await fireEvent.click(within(panel).getByRole('button', { name: new RegExp(tp('results.safe', s.scan!.counts.safe)) }));
    const safe = screen.getByRole('region', { name: 'Bez uwag' });
    expect(within(safe).getAllByRole('article')).toHaveLength(s.scan!.counts.safe);
  });

  test('simple mode: verdict sections, “to review” and “no issues” folded by default', async () => {
    const { s, ctl } = await scanned();
    const review = s.scan!.apps.filter((a) => a.verdict === 'review');
    expect(screen.getByRole('region', { name: 'Szkodliwe' })).toBeTruthy();
    // Pusta kategoria nie ma już własnego regionu — tylko wiersz „Podejrzane 0 — nic nie znaleziono”.
    expect(screen.queryByRole('region', { name: 'Podejrzane' })).toBeNull();
    expect(screen.getByTestId('empty-verdicts').textContent).toMatch(/Podejrzane.*nic nie znaleziono/);
    const toggle = screen.getByRole('button', { name: /^Do sprawdzenia/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('article', { name: review[0].name })).toBeNull();
    await fireEvent.click(toggle);
    expect(screen.getByRole('article', { name: review[0].name })).toBeTruthy();
    expect(s.openGroups.review).toBe(true);
    await ctl.setMode('expert');
    await ctl.setMode('simple');
    await tick();
    expect(screen.queryByRole('article', { name: review[0].name })).toBeNull();
  });

  // Telefon bez szkodliwych i podejrzanych, z aplikacjami do sprawdzenia (werdykty podmienione w skanie).
  async function onlyReview() {
    const env = await scanned();
    env.s.scan = { ...env.s.scan!, apps: env.s.scan!.apps.map((a) => (a.verdict === 'malicious' || a.verdict === 'suspicious' ? { ...a, verdict: 'review' as const } : a)) };
    await tick();
    return env;
  }

  test('simple mode: no malicious and no suspicious fold into one line', async () => {
    await onlyReview();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Podejrzane' })).toBeNull();
    const line = screen.getByTestId('empty-verdicts');
    expect(line.textContent).toMatch(/Szkodliwe/);
    expect(line.textContent).toMatch(/Podejrzane/);
    expect(line.textContent).toMatch(/nic nie znaleziono/);
  });

  test('simple mode: one suspicious app keeps its section, the line lists only malicious', async () => {
    const { s } = await onlyReview();
    const first = s.scan!.apps.find((a) => a.verdict === 'review')!.package;
    s.scan = { ...s.scan!, apps: s.scan!.apps.map((a) => (a.package === first ? { ...a, verdict: 'suspicious' as const } : a)) };
    await tick();
    expect(screen.getByRole('region', { name: 'Podejrzane' })).toBeTruthy();
    const line = screen.getByTestId('empty-verdicts');
    expect(line.textContent).toMatch(/Szkodliwe/);
    expect(line.textContent).not.toMatch(/Podejrzane/);
  });

  test('expert mode: the line sits above the table; searching to nothing does not show “nothing found”', async () => {
    const { ctl, s } = await onlyReview();
    await ctl.setMode('expert');
    await tick();
    const table = screen.getByRole('group', { name: 'Tabela aplikacji' });
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(within(table).getByTestId('empty-verdicts').textContent).toMatch(/Szkodliwe.*Podejrzane.*nic nie znaleziono/);
    // Wiersz nad grupą „Do sprawdzenia”.
    const line = within(table).getByTestId('empty-verdicts');
    const review = within(table).getByRole('region', { name: 'Do sprawdzenia' });
    expect(line.compareDocumentPosition(review) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    s.query = 'zzzz-brak-takiej-aplikacji';
    await tick();
    expect(screen.queryByTestId('empty-verdicts')).toBeNull();
    expect(screen.queryByText(/nic nie znaleziono/)).toBeNull();
  });

  test('clean phone, simple: the clean state, no empty danger lines, folded “no issues”', async () => {
    const { ctl } = await scanned('clean');
    await ctl.setMode('simple');
    await tick();
    expect(screen.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(screen.getByRole('button', { name: /^Bez uwag/ }).getAttribute('aria-expanded')).toBe('false');
  });

  test('clean phone, expert: clean state above the table, search and filters, folded “no issues” reachable', async () => {
    const { ctl, s } = await scanned('clean');
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeTruthy();
    expect(screen.getByRole('searchbox', { name: 'Szukaj aplikacji lub pakietu' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Filtry' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Podejrzane' })).toBeNull();
    const table = screen.getByRole('group', { name: 'Tabela aplikacji' });
    const toggle = within(table).getByRole('button', { name: /^Bez uwag/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelectorAll('#group-safe')).toHaveLength(1);
    await fireEvent.click(toggle);
    const rows = appRows();
    expect(rows.length).toBeGreaterThan(1);
    const second = s.scan!.apps[1];
    await fireEvent.click(rows.find((r) => r.textContent?.includes(second.package))!);
    const panel = screen.getByRole('complementary', { name: 'Szczegóły aplikacji' });
    expect(within(panel).getByText(second.name)).toBeTruthy();
  });

  test('nothing selected: the panel says so and the fix button is disabled', async () => {
    const { s } = await scanned();
    s.selection = {};
    await tick();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    expect(within(panel).getByText('Zaznacz aplikacje albo witryny, które chcesz naprawić.')).toBeTruthy();
    const fix = within(panel).getByRole('button', { name: 'Podsumowanie (0)' }) as HTMLButtonElement;
    expect(fix.disabled).toBe(true);
  });

  test('clean phone', async () => {
    const { s } = await scanned('clean');
    expect(screen.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeTruthy();
    expect(screen.getByText(`W zakresie wykonanego skanu · sprawdzone aplikacje: ${s.scan!.counts.total}`)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Podsumowanie (0)' }) as HTMLButtonElement)
      .disabled).toBe(true);
  });

  test('mode switch in the header', async () => {
    const { s } = await scanned();
    await fireEvent.click(screen.getByRole('button', { name: 'Ekspert' }));
    await vi.waitFor(() => expect(s.settings.mode).toBe('expert'));
  });

  test('expert mode: sections, search, keyboard, evidence panel', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByRole('columnheader', { name: 'Problemy' })).toBeTruthy();
    expect(screen.queryByRole('columnheader', { name: 'Powód' })).toBeNull();
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
    await fireEvent.input(screen.getByRole('searchbox', { name: 'Szukaj aplikacji lub pakietu' }), { target: { value: 'forecast' } });
    expect(appRows()).toHaveLength(2);
    expect(within(panel).getByText('com.wlive.forecast')).toBeTruthy();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: 'zzz-nothing' } });
    expect(within(screen.getByRole('group', { name: 'Tabela aplikacji' })).queryAllByRole('row')).toHaveLength(0);
    expect(within(panel).getByText('Wybierz aplikację w tabeli.')).toBeTruthy();
    await fireEvent.keyDown(table, { key: 'ArrowUp' });
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Akcja com.wlive.forecast' }),
      { target: { value: 'silence' } });
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    const safeApp = s.scan!.apps.find((a) => a.verdict === 'safe')!;
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: safeApp.package } });
    expect(screen.getByRole('checkbox', { name: safeApp.package })).toBeTruthy(); // zwinięta grupa sama się rozwija
    expect(s.openGroups.safe).toBeUndefined();
    await fireEvent.input(screen.getByRole('searchbox'), { target: { value: '' } });
    expect(screen.queryByRole('checkbox', { name: safeApp.package })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /^Bez uwag/ }));
    expect(appRows()).toHaveLength(s.scan!.apps.length + 1);
  });
  test('expert filters: problem type chips and source list narrow the table, clear brings it back', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    const menu = screen.getByRole('button', { name: 'Filtry' });
    expect(menu.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(menu);
    const types = screen.getByRole('group', { name: 'Rodzaj problemu' });
    const ads = within(types).getByRole('button', { name: /^Reklamy/ });
    expect(ads.getAttribute('aria-pressed')).toBe('false');
    await fireEvent.click(ads);
    expect(ads.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Filtry · 1' })).toBeTruthy();
    expect(appRows()).toHaveLength(2);
    expect(screen.getByRole('checkbox', { name: 'com.clean.pro.boost' })).toBeTruthy();
    const source = screen.getByRole('combobox', { name: 'Filtr źródła' });
    expect(within(source).getByRole('option', { name: 'Wszystkie źródła' })).toBeTruthy();
    await fireEvent.change(source, { target: { value: 'Sklep Play' } });
    expect(within(screen.getByRole('group', { name: 'Tabela aplikacji' })).queryAllByRole('row')).toHaveLength(0);
    expect(screen.getByText('Brak aplikacji pasujących do filtrów.')).toBeTruthy();
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('group', { name: 'Rodzaj problemu' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść filtry' }));
    expect(appRows()).toHaveLength(flagged.length + 1);
    expect(s.categoryFilter).toEqual([]);
    expect(s.sourceFilter).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Filtry' }));
    await fireEvent.change(screen.getByRole('combobox', { name: 'Filtr źródła' }), { target: { value: 'Chrome' } });
    ctl.newScan();
    expect(s.sourceFilter).toBeNull();
  });

  test('expert filters: the popover stays open after clearing filters from inside it', async () => {
    const { ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Filtry' }));
    await fireEvent.click(within(screen.getByRole('group', { name: 'Rodzaj problemu' })).getByRole('button', { name: /^Reklamy/ }));
    // Przeglądarka opróżnia mikrozadania między słuchaczami zdarzenia, więc przycisk znika przed oknem.
    const flush = () => flushSync();
    document.addEventListener('click', flush);
    await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść filtry' }));
    document.removeEventListener('click', flush);
    expect(screen.getByRole('group', { name: 'Rodzaj problemu' })).toBeTruthy();
    await fireEvent.click(document.body);
    expect(screen.queryByRole('group', { name: 'Rodzaj problemu' })).toBeNull();
  });

  test('expert filters: “Outside the Play Store” keeps only non-Play, non-system apps', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    const outside = s.scan!.apps.filter((a) => a.verdict !== 'safe' && !a.is_system && !a.from_play);
    await fireEvent.click(screen.getByRole('button', { name: 'Filtry' }));
    const source = screen.getByRole('combobox', { name: 'Filtr źródła' });
    await fireEvent.change(source, { target: { value: '__non_play__' } });
    expect(within(source).getByRole('option', { name: /^Spoza Sklepu Play/ })).toBeTruthy();
    expect(appRows()).toHaveLength(outside.length + 1);
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
  const notesLine = () => screen.getByRole('region', { name: 'Uwagi do skanu' });
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
    expect(notesLine().textContent).toContain(t('notice.short.incomplete'));
    await openNotes();
    expect(screen.getByText(t('summary.incomplete', { count: n, names: GAP.label }))).toBeTruthy();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    const toggle = within(panel).getByRole('button', { name: new RegExp(tp('results.safe_incomplete', n)) });
    await fireEvent.click(toggle);
    const region = screen.getByRole('region', { name: 'Bez uwag' });
    expect(within(region).getAllByText(t('results.incomplete'))).toHaveLength(n);
  });

  test('a failed or partial collector alone still shows the warn banner', async () => {
    const { s } = await scanned('clean');
    s.scan = { ...s.scan!, collectors: { ...s.scan!.collectors,
      partial: [{ name: 'appops', count: 1 }] } };
    await tick();
    expect(notesLine().textContent).toContain(t('notice.short.incomplete'));
    await openNotes();
    expect(screen.getByText(t('summary.incomplete', { count: 0, names: 'appops' }))).toBeTruthy();
  });

  test('collector errors under the incomplete note: expert only', async () => {
    const { s, ctl } = await scanned('clean');
    devicePolicyFailed(s);
    await tick();
    const line = t('expert.collector_failed', { name: 'device_policy', error: 'timeout' });
    await openNotes();
    expect(screen.queryByText(line)).toBeNull();
    await ctl.setMode('expert');
    await tick();
    await openNotes();
    expect(screen.getByText(line)).toBeTruthy();
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
    // „Stan telefonu nie odczytany” należy do zakładki „Telefon”, więc linia uwag aplikacji znika.
    expect(screen.queryByRole('region', { name: 'Uwagi do skanu' })?.textContent ?? '').not.toContain(t('notice.short.profiles_unknown'));
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
    s.undoResult = { order: 'ZS', status: 'partially_undone', status_label: '', errors: ['Brak kopii aplikacji.'], admin_not_restored: false,
      sites_total: 0, sites_restored: 0, restored_sites: [], firefox_debugging: false, interrupted: [] };
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
      largest_bytes: 3 * GB, limit_bytes: 10 * GB, effective_bytes: 2 * GB, free_bytes: 4 * GB, eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null, scope: 'all' });
    await vi.waitFor(() => expect(apkHint()).toMatch(/Analiza pobierze ok. 7,2 GB \(142 aplikacje\)/));
    expect(apkHint()).toMatch(/Na dysku jest miejsce na 2,0 GB/);
    expect(tp('apk_cache.estimate', 5, { size: '1,0 GB' })).toBe('Analiza pobierze ok. 1,0 GB (5 aplikacji)');
    bridge.emit('apk:question', { job_id: 'job-9', kind: 'no_space', to_fetch_bytes: 7.2 * GB, total_bytes: 7.2 * GB,
      apps: 142, unknown: 0, cached: 0, largest_bytes: 3 * GB, limit_bytes: 10 * GB, effective_bytes: 2 * GB, free_bytes: 4 * GB,
      eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null });
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
      effective_bytes: 10 * GB, free_bytes: 50 * GB, eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null };
    s.apk = { ...s.apk, running: true };
    bridge.emit('apk:estimate', { ...base, to_fetch_bytes: 0, apps: 89, cached: 89, scope: 'all' });
    await vi.waitFor(() => expect(apkHint()).toBe(
      'Pliki wszystkich aplikacji do analizy (89) są już na komputerze — nic nie trzeba pobierać.'));
    bridge.emit('apk:estimate', { ...base, to_fetch_bytes: 30 * 1024 ** 2, apps: 89, cached: 87, scope: 'all' });
    await vi.waitFor(() => expect(apkHint()).toBe(
      'Analiza pobierze ok. 30 MB (2 z 89 aplikacji, pozostałe są już na komputerze).'));
  });

  test('find the ad source: header button swaps the side panel, back and the plan close it', async () => {
    const { s } = await scanned();
    expect(screen.queryByRole('button', { name: 'Kto to wyświetla?' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Znajdź źródło reklamy' }));
    const panel = screen.getByRole('complementary', { name: 'Znajdź źródło reklamy' });
    expect(within(panel).getByRole('button', { name: 'Kto to wyświetla?' })).toBeTruthy();
    await fireEvent.click(within(panel).getByRole('button', { name: 'Wróć' }));
    expect(screen.getByRole('complementary', { name: 'Plan naprawy' })).toBeTruthy();
    s.incident = { recording: true, marks: 0, result: null };
    await tick();
    expect(screen.getByRole('button', { name: /^Znajdź źródło reklamy/ }).querySelector('[data-recording]')).not.toBeNull();
  });

  test('expert row: one tile per symptom named by the category', async () => {
    const { ctl, s } = await scanned();
    await ctl.setMode('expert');
    await tick();
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    const row = screen.getByRole('checkbox', { name: boost.package }).closest('tr')!;
    expect(within(row).getAllByRole('img').map((x) => x.getAttribute('aria-label')))
      .toEqual(boost.symptoms.map((sy) => t(`category.${sy.category}`)));
    expect(row.querySelector('[data-more]')).toBeNull();
    expect(within(row).getAllByRole('img').some((x) => x.hasAttribute('tabindex'))).toBe(false);
  });

  test('simple side panel lists only apps with an action, no "bez zmian"', async () => {
    const { s } = await scanned();
    s.selection = {};
    await tick();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    expect(within(panel).queryByText(/bez zmian/)).toBeNull();
  });

  test('header order: mode, find source, screen view, rescan; icon buttons have names', async () => {
    await scanned();
    const header = screen.getByRole('main').querySelector('header')!;
    const names = within(header).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent!.trim());
    expect(names).toEqual(['Prosty', 'Ekspert', 'Znajdź źródło reklamy', 'Włącz podgląd ekranu', 'Skanuj ponownie']);
  });

  test('find source tooltip and name while recording', async () => {
    const { s } = await scanned();
    s.incident = { recording: true, marks: 0, result: null };
    await tick();
    const btn = screen.getByRole('button', { name: /^Znajdź źródło reklamy/ });
    expect(btn.getAttribute('aria-label')).toBe('Znajdź źródło reklamy — trwa nagrywanie');
    expect(btn.querySelector('[data-recording]')).not.toBeNull();
  });

  test('mirror button toggles the screen view and reflects pressed', async () => {
    const { s, bridge } = await scanned();
    const btn = () => within(screen.getByRole('main').querySelector('header')!).getByRole('button', { name: /podgląd ekranu/i });
    expect(btn().getAttribute('aria-pressed')).toBe('false');
    expect(btn().getAttribute('aria-label')).toBe('Włącz podgląd ekranu');
    await fireEvent.click(btn());
    await vi.waitFor(() => expect(s.mirror.state).toBe('running'));
    await tick();
    expect(bridge.calls.some((c) => c.method === 'mirror_start')).toBe(true);
    expect(btn().getAttribute('aria-pressed')).toBe('true');
    expect(btn().getAttribute('aria-label')).toBe('Wyłącz podgląd ekranu');
    await fireEvent.click(btn());
    await vi.waitFor(() => expect(s.mirror.state).toBe('stopped'));
    await tick();
    expect(bridge.calls.some((c) => c.method === 'mirror_stop')).toBe(true);
    expect(btn().getAttribute('aria-pressed')).toBe('false');
  });

  test('mirror button is disabled while starting and when scrcpy is missing', async () => {
    const { s } = await scanned();
    const btn = () => within(screen.getByRole('main').querySelector('header')!).getByRole('button', { name: /podgląd|scrcpy/i }) as HTMLButtonElement;
    s.mirror = { ...s.mirror, serial: s.device!.serial, state: 'starting' };
    await tick();
    expect(btn().disabled).toBe(true);
    expect(btn().getAttribute('aria-label')).toBe('Uruchamianie podglądu…');
    s.mirror = { ...s.mirror, serial: null, state: 'stopped', available: false };
    await tick();
    expect(btn().disabled).toBe(true);
    expect(btn().getAttribute('aria-label')).toContain('brak dołączonego scrcpy');
  });

  test('mirror button is disabled without a device', async () => {
    const { s } = await scanned();
    s.device = null;
    await tick();
    expect((within(screen.getByRole('main').querySelector('header')!).getByRole('button', { name: 'Włącz podgląd ekranu' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Results: APK analysis in progress and bulk group actions', () => {
  test('APK analysis on a clean phone: progress state instead of the green all clear', async () => {
    const { s } = await scanned('clean');
    s.apk = { done: 5, total: 140, running: true, changed: [], eta: null };
    await tick();
    expect(screen.queryByRole('heading', { name: t('results.clean_title') })).toBeNull();
    expect(screen.getByRole('heading', { name: t('results.apk_title') })).toBeTruthy();
    expect(apkHint()).toBe(t('results.apk_sub'));
    expect(screen.getByRole('progressbar', { name: t('summary.apk_running', { done: 5, total: 140 }) })).toBeTruthy();
    s.apk = { ...s.apk, running: false };
    await tick();
    expect(screen.getByRole('heading', { name: t('results.clean_title') })).toBeTruthy();
  });

  test('simple mode: select all in a group asks first when it would disable, clearing does not ask', async () => {
    const { s } = await scanned();
    s.selection = {};
    await tick();
    const region = screen.getByRole('region', { name: 'Szkodliwe' });
    const all = within(region).getByRole('checkbox', { name: t('bulk.select_all_in', { group: 'Szkodliwe' }) });
    await fireEvent.click(all);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('bulk.check'))).toBeTruthy();
    expect(s.selection).toEqual({});
    await fireEvent.click(within(dialog).getByRole('button', { name: t('bulk.confirm') }));
    expect(s.selection).toEqual({ 'com.clean.pro.boost': 'disable' });
    await tick();
    expect((all as HTMLInputElement).checked).toBe(true);
    await fireEvent.click(all);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(s.selection).toEqual({});
  });

  test('select all header follows the rows even after the browser left the box out of step', async () => {
    const { s, ctl } = await scanned();
    // „Do sprawdzenia” z kilkoma aplikacjami, żeby przejść przez stan „część zaznaczona”.
    s.scan = { ...s.scan!, apps: s.scan!.apps.map((a) => (a.verdict === 'safe' ? { ...a, verdict: 'review' as const } : a)) };
    ctl.setGroupOpen('review', true);
    s.selection = {};
    await tick();
    const region = screen.getByRole('region', { name: 'Do sprawdzenia' });
    const all = within(region).getByRole('checkbox', { name: t('bulk.select_all_in', { group: 'Do sprawdzenia' }) }) as HTMLInputElement;
    const one = s.scan.apps.find((a) => a.verdict === 'review')!.package;
    expect(all.checked).toBe(false);
    all.checked = true; // Chromium przywraca stan pola po kliknięciu, już po zapisie Svelte
    s.selection = { [one]: 'silence' };
    await tick();
    expect(all.checked).toBe(false);
    expect(all.indeterminate).toBe(true);
    s.selection = {};
    await tick();
    expect(all.checked).toBe(false);
    expect(all.indeterminate).toBe(false);
  });

  test('bulk action: silence applies at once, remove asks and warns about data', async () => {
    const { s, ctl } = await scanned();
    ctl.setGroupOpen('review', true);
    s.selection = { 'com.wlive.forecast': 'disable' };
    await tick();
    const region = screen.getByRole('region', { name: 'Do sprawdzenia' });
    const action = within(region).getByRole('combobox', { name: t('bulk.action_in', { group: 'Do sprawdzenia' }) });
    await fireEvent.change(action, { target: { value: 'silence' } });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await fireEvent.change(action, { target: { value: 'remove' } });
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(t('bulk.data_lost'))).toBeTruthy();
    await fireEvent.click(within(dialog).getByRole('button', { name: t('common.cancel') }));
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await fireEvent.change(action, { target: { value: 'remove' } });
    await fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: t('bulk.apply') }));
    expect(s.selection['com.wlive.forecast']).toBe('remove');
  });

  test('expert mode: bulk controls on flagged groups only; long source names are cut with the full name on hover', async () => {
    const { s, ctl } = await scanned();
    await ctl.setMode('expert');
    ctl.setGroupOpen('safe', true);
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    s.scan = { ...s.scan!, apps: s.scan!.apps.map((a) => a.package === boost.package
      ? { ...a, source: { label: 'com.some.very.long.vendor.store', days: 3 } } : a) };
    await tick();
    const table = screen.getByRole('group', { name: 'Tabela aplikacji' });
    expect(within(table).getByRole('checkbox', { name: t('bulk.select_all_in', { group: 'Szkodliwe' }) })).toBeTruthy();
    expect(within(table).queryByRole('checkbox', { name: t('bulk.select_all_in', { group: 'Bez uwag' }) })).toBeNull();
    const cell = within(table).getByText('com.some.very.long.vendor.store');
    expect(cell.classList.contains('truncate')).toBe(true);
    expect(cell.getAttribute('title')).toBe('com.some.very.long.vendor.store');
  });
});

describe('Results: manual mode (tryb ręczny)', () => {
  const snap = (v: unknown) => JSON.parse(JSON.stringify(v));

  test('manual mode: no view switch, the search title, no verdict groups and never the all-clear title', async () => {
    const { ctl, s, bridge } = await scanned('clean');
    expect(screen.getByRole('group', { name: t('results.mode') })).toBeTruthy();
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual', on_demand: [] } });
    await tick();
    expect(screen.queryByRole('group', { name: t('results.mode') })).toBeNull();
    expect(screen.getByRole('heading', { name: t('manual.title') })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: t('results.clean_title') })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Bez uwag' })).toBeNull();
    expect(screen.queryByRole('button', { name: new RegExp(tp('results.safe', s.scan!.counts.safe)) })).toBeNull();
    expect(screen.getByRole('searchbox', { name: t('manual.search') })).toBeTruthy();
    // Domyślny tryb Ekspert też nie pokazuje tabeli z werdyktami ani panelu dowodów.
    await ctl.setMode('expert');
    await tick();
    expect(screen.queryByRole('group', { name: 'Tabela aplikacji' })).toBeNull();
    expect(screen.getByRole('complementary', { name: t('panel.plan') })).toBeTruthy();
    // Częściowy (po analizie na żądanie) — nadal bez grup i przełącznika.
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'partial', on_demand: [s.scan!.apps[0].package] } });
    await tick();
    expect(screen.queryByRole('group', { name: t('results.mode') })).toBeNull();
    expect(screen.getByRole('heading', { name: t('manual.title') })).toBeTruthy();
  });

  test('“ask” setting: no verdicts, title or plan before and during the question; groups after choosing full', async () => {
    const { ctl, s, bridge } = await scanned();
    await ctl.saveSettings({ apk_mode_default: 'ask' });
    s.job = { id: 'j1', kind: 'apk' };
    bridge.emit('scan:done', { scan: { ...snap(s.scan), apk_mode: 'pending', on_demand: [] }, interrupted: [], client: null });
    await tick();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe');
    const panel = () => screen.getByRole('complementary', { name: t('panel.plan') });
    const hidden = () => {
      expect(s.selection).toEqual({});
      expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
      expect(screen.queryByRole('heading', { name: tp('results.title', flagged.length) })).toBeNull();
      expect(screen.getByRole('heading', { name: t('results.apk_title') })).toBeTruthy();
      expect(screen.queryByRole('group', { name: t('results.mode') })).toBeNull();
      expect((within(panel()).getByRole('button', { name: t('actions.fix', { count: 0 }) }) as HTMLButtonElement).disabled).toBe(true);
    };
    hidden();
    expect(apkHint()).toBe(t('results.apk_sub'));
    // Nawet wymuszone zaznaczenie nie trafia do panelu, dopóki tryb nie jest wybrany.
    s.selection = { [flagged[0].package]: 'disable' };
    await tick();
    expect(within(panel()).queryByText(flagged[0].name)).toBeNull();
    s.selection = {};
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 12, eta_s: 90, eta_kind: 'measured', eta_min_s: 90, eta_max_s: 90 });
    await tick();
    hidden();
    await fireEvent.click(screen.getByRole('button', { name: new RegExp(t('apk_mode.full')) }));
    await tick();
    expect(screen.getByRole('region', { name: 'Szkodliwe' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: tp('results.title', flagged.length) })).toBeTruthy();
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'full' }, job_id: 'j1' });
    await tick();
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
    expect(within(panel()).getByText(s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!.name)).toBeTruthy();
  });

  test('mode question: the choice card instead of the groups', async () => {
    const { s, bridge } = await scanned();
    s.job = { id: 'j1', kind: 'apk' };
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 12, eta_s: 90, eta_kind: 'measured', eta_min_s: 90, eta_max_s: 90 });
    await tick();
    expect(screen.getByRole('button', { name: new RegExp(t('apk_mode.full')) })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(screen.queryByRole('group', { name: t('results.mode') })).toBeNull();
    expect(screen.getByRole('heading', { name: t('results.apk_title') })).toBeTruthy();
  });

  test('full analysis: remaining time and “stop and search by hand”; not for a selected-only or deep job', async () => {
    const { s, bridge } = await scanned('clean');
    s.job = { id: 'j1', kind: 'apk' };
    s.apkScope = 'all';
    s.apk = { done: 5, total: 140, running: true, changed: [], eta: 30 };
    await tick();
    expect(screen.getByText(t('eta.under_min'))).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: t('apk_mode.stop_to_manual') }));
    expect(bridge.calls.some((c) => c.method === 'stop_apk_to_manual')).toBe(true);
    s.apk = { ...s.apk, eta: 600 };
    await tick();
    expect(screen.getByText(t('eta.min', { n: 10 }))).toBeTruthy();
    s.apkScope = 'selected';
    await tick();
    expect(screen.queryByRole('button', { name: t('apk_mode.stop_to_manual') })).toBeNull();
    s.apkScope = 'all';
    s.job = { id: 'j2', kind: 'deep' };
    await tick();
    expect(screen.queryByRole('button', { name: t('apk_mode.stop_to_manual') })).toBeNull();
  });
});

describe('Results: phone state', () => {
  async function scannedWithChecks() {
    const env = await setupCtl('adware', { checks: [CHECKS_SAMPLE] });
    render(App, { props: { ctl: env.ctl } });
    await env.ctl.startScan();
    await vi.waitFor(() => expect(env.s.job).toBeNull());
    await tick();
    return env;
  }

  test('the section lives in the “Telefon” tab, not above the app list', async () => {
    await scannedWithChecks();
    expect(screen.queryByRole('region', { name: 'Stan telefonu' })).toBeNull();
    expect(screen.getByRole('region', { name: 'Szkodliwe' })).toBeTruthy();
    await openPhone();
    expect(screen.getByRole('region', { name: 'Stan telefonu' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
  });

  test('an unreadable phone state is a notice, not an empty or “all clear” section', async () => {
    await scanned();
    await openPhone();
    expect(screen.queryByRole('region', { name: 'Stan telefonu' })).toBeNull();
    await fireEvent.click(within(screen.getByRole('region', { name: 'Uwagi do skanu' })).getByRole('button', { name: 'Więcej' }));
    expect(screen.getByText(/Nie dało się odczytać stanu telefonu/)).toBeTruthy();
  });

  test('a ticked site makes a runnable plan: the panel counts it and the confirmation lists it', async () => {
    const { s, bridge } = await scannedWithChecks();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    const before = Object.keys(s.selection).length;
    await openPhone();
    await fireEvent.click(screen.getByRole('switch', { name: 'Wycisz tanie-bilety.example' }));
    expect(within(panel).getByText('tanie-bilety.example')).toBeTruthy();
    await fireEvent.click(within(panel).getByRole('button', { name: `Podsumowanie (${before + 1})` }));
    const confirm = await screen.findByRole('region', { name: 'Plan naprawy' });
    expect(within(confirm).getByRole('list', { name: 'Ustawienia witryn (1)' })).toBeTruthy();
    // przeglądarka z ikoną i nazwą, pod nią sam adres witryny — bez zdania z nazwą przeglądarki
    expect(within(within(confirm).getByRole('list', { name: 'Chrome' })).getByText('tanie-bilety.example')).toBeTruthy();
    expect(confirm.textContent).not.toContain('Wyłączenie powiadomień');
    expect(bridge.calls.filter((c) => c.method === 'preview_plan').at(-1)!.args[2]).toEqual([CHECKS_SAMPLE.browsers[0].sites[0].fix]);
  });

  test('with no apps selected, a ticked site alone enables the summary button', async () => {
    const { s } = await scannedWithChecks();
    s.selection = {};
    await tick();
    const panel = screen.getByRole('complementary', { name: 'Plan naprawy' });
    expect((within(panel).getByRole('button', { name: 'Podsumowanie (0)' }) as HTMLButtonElement).disabled).toBe(true);
    await openPhone();
    await fireEvent.click(screen.getByRole('switch', { name: 'Wycisz wiadomosci.example' }));
    expect((within(panel).getByRole('button', { name: 'Podsumowanie (1)' }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('Results: “Aplikacje” and “Telefon” tabs', () => {
  const CHROME = CHECKS_SAMPLE.browsers[0];
  const check = (browsers: CheckBrowser[]): DeviceCheck =>
    ({ id: 'site_notifications', state: 'review', state_label: 'Do sprawdzenia', browsers });
  const snap = (v: unknown) => JSON.parse(JSON.stringify(v));
  const unreadable = t('notice.short.checks_unreadable');

  test('after a scan: the tab bar, apps first; the site card only after switching to “Telefon”', async () => {
    const { s } = await scanned('adware', [CHECKS_SAMPLE]);
    expect(screen.getByRole('tablist', { name: t('repair_tabs.label') })).toBeTruthy();
    expect(tab('Aplikacje').getAttribute('aria-selected')).toBe('true');
    expect(tab('Telefon').getAttribute('aria-selected')).toBe('false');
    const apps = screen.getByRole('tabpanel');
    expect(apps.id).toBe('repair-panel-apps');
    expect(apps.getAttribute('aria-labelledby')).toBe('repair-tab-apps');
    expect(screen.queryByRole('heading', { name: 'Powiadomienia z witryn' })).toBeNull();
    expect(within(apps).getByRole('region', { name: 'Szkodliwe' })).toBeTruthy();
    await openPhone();
    expect(s.repairTab).toBe('phone');
    const phone = screen.getByRole('tabpanel');
    expect(phone.id).toBe('repair-panel-phone');
    expect(phone.getAttribute('aria-labelledby')).toBe('repair-tab-phone');
    expect(within(phone).getByRole('heading', { name: 'Powiadomienia z witryn' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Szkodliwe' })).toBeNull();
    expect(screen.queryByRole('article')).toBeNull();
  });

  test('expert table (and its arrow keys) only on “Aplikacje”', async () => {
    const { ctl } = await scanned();
    await ctl.setMode('expert');
    await tick();
    expect(screen.getByRole('group', { name: 'Tabela aplikacji' })).toBeTruthy();
    await openPhone();
    expect(screen.queryByRole('group', { name: 'Tabela aplikacji' })).toBeNull();
  });

  test('the apps badge counts flagged apps', async () => {
    const { s } = await scanned();
    const flagged = s.scan!.apps.filter((a) => a.verdict !== 'safe').length;
    expect(tab('Aplikacje').textContent).toContain(String(flagged));
  });

  test('“phone state unreadable” is a phone notice, not an apps notice', async () => {
    await scanned(); // nagrany skan: stan telefonu „nie udało się odczytać”
    expect(screen.queryByRole('region', { name: 'Uwagi do skanu' })?.textContent ?? '').not.toContain(unreadable);
    await openPhone();
    expect(screen.getByRole('region', { name: 'Uwagi do skanu' }).textContent).toContain(unreadable);
  });

  test('the tab bar is there in manual mode, without an apps badge', async () => {
    const { s, bridge } = await scanned('clean');
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual', on_demand: [] } });
    await tick();
    const panel = screen.getByRole('tabpanel');
    expect(within(panel).getByRole('searchbox', { name: t('manual.search') })).toBeTruthy();
    expect(screen.getByRole('tablist', { name: t('repair_tabs.label') })).toBeTruthy();
    expect(tab('Aplikacje').textContent?.trim()).toBe('Aplikacje');
  });

  test('the tab bar is there while the analysis mode is being chosen; the choice is in “Aplikacje”', async () => {
    const { s, bridge } = await scanned();
    s.job = { id: 'j1', kind: 'apk' };
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 12, eta_s: 90, eta_kind: 'measured', eta_min_s: 90, eta_max_s: 90 });
    await tick();
    expect(screen.getByRole('tablist', { name: t('repair_tabs.label') })).toBeTruthy();
    expect(tab('Aplikacje').textContent?.trim()).toBe('Aplikacje');
    expect(within(screen.getByRole('tabpanel')).getByRole('button', { name: new RegExp(t('apk_mode.full')) })).toBeTruthy();
  });

  test('clean apps, things to do on the phone: same title, a link under the illustration switches tabs', async () => {
    const { s } = await scanned('clean', [check([CHROME])]);
    expect(screen.getByRole('heading', { name: t('results.clean_title') })).toBeTruthy();
    const link = screen.getByRole('button', { name: 'W zakładce Telefon: 2 rzeczy do sprawdzenia' });
    await fireEvent.click(link);
    expect(s.repairTab).toBe('phone');
    expect(tab('Telefon').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('heading', { name: 'Powiadomienia z witryn' })).toBeTruthy();
  });

  test('clean apps, phone unreadable: the “not everything could be read” link', async () => {
    const { s } = await scanned('clean');
    await fireEvent.click(screen.getByRole('button', { name: 'W zakładce Telefon: nie wszystko udało się odczytać' }));
    expect(s.repairTab).toBe('phone');
  });

  test('clean apps, phone all fine: no link under the illustration', async () => {
    await scanned('clean', [{ ...check([{ ...CHROME, sites: [CHROME.sites[2]] }]), state: 'ok' }]);
    expect(screen.getByRole('heading', { name: t('results.clean_title') })).toBeTruthy();
    expect(within(tab('Telefon')).getByRole('img', { name: t('repair_tabs.phone_ok') })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^W zakładce Telefon/ })).toBeNull();
  });

  test('a scan without phone checks: “Telefon” has a tick and says there is nothing to check', async () => {
    await scanned('clean', []);
    expect(within(tab('Telefon')).getByRole('img', { name: t('repair_tabs.phone_ok') })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^W zakładce Telefon/ })).toBeNull();
    await openPhone();
    expect(screen.getByText('Nic do sprawdzenia na tym telefonie.')).toBeTruthy();
  });

  test('the phone tab with checks to show has no “nothing to check” line', async () => {
    await scanned('adware', [CHECKS_SAMPLE]);
    await openPhone();
    expect(screen.queryByText('Nic do sprawdzenia na tym telefonie.')).toBeNull();
  });
});

describe('Results: Firefox re-reads in the background, whichever tab is open', () => {
  const FIREFOX = CHECKS_SAMPLE.browsers[2];
  const SAMSUNG = CHECKS_SAMPLE.browsers[1];
  const check = (browsers: CheckBrowser[]): DeviceCheck =>
    ({ id: 'site_notifications', state: 'review', state_label: 'Do sprawdzenia', browsers });
  const rechecks = (env: { bridge: { calls: { method: string }[] } }) =>
    env.bridge.calls.filter((c) => c.method === 'recheck_site_notifications').length;
  const site = (host: string) => ({ host, origin: `https://${host}`, blocked: false, active: false,
    fix: `site_perm:org.mozilla.firefox:https://${host}`, fix_label: `Blokada powiadomień: ${host} (Firefox)` });

  afterEach(() => vi.useRealTimers());

  async function resultsWith(checks: DeviceCheck[]) {
    const env = await setupCtl('adware', { checks });
    await env.ctl.startScan();
    await vi.waitFor(() => expect(env.s.job).toBeNull());
    vi.useFakeTimers();
    const view = render(Results, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    return { ...env, view };
  }

  test('on “Aplikacje”: every 5 s a cheap re-read; once sites show up the tab count grows and polling ends', async () => {
    const env = await resultsWith([check([FIREFOX])]);
    expect(env.s.repairTab).toBe('apps');
    expect(tab('Telefon').textContent).toContain('1');
    expect(rechecks(env)).toBe(0);
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(1);
    // w tle tylko tani odczyt gniazda debugowania
    expect(env.bridge.calls.filter((c) => c.method === 'recheck_site_notifications').at(-1)?.args).toEqual([true]);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(rechecks(env)).toBe(3);
    // Serwisant włączył debugowanie: następny odczyt oddaje witryny i polling się kończy.
    env.bridge.setChecks([check([{ ...FIREFOX, mode: 'rdp', read: 'ok', rdp_hint: false,
      sites: [site('push.example'), site('promo.example')] }])]);
    await vi.advanceTimersByTimeAsync(5000);
    await tick();
    expect(env.s.scan!.device_checks[0].browsers[0].rdp_hint).toBe(false);
    expect(tab('Telefon').textContent).toContain('2');
    const after = rechecks(env);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(rechecks(env)).toBe(after);
    env.view.unmount();
  });

  test('the “Telefon” tab shows the instruction and no retry button', async () => {
    const env = await resultsWith([check([FIREFOX])]);
    await fireEvent.click(tab('Telefon'));
    expect(screen.getByText(/Zdalne debugowanie przez USB/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Spróbuj|Ponów|Sprawdź ponownie/ })).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(1);
    env.view.unmount();
  });

  test('polling stops when the repair screen leaves', async () => {
    const env = await resultsWith([check([FIREFOX])]);
    await vi.advanceTimersByTimeAsync(5000);
    env.view.unmount();
    const before = rechecks(env);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(rechecks(env)).toBe(before);
  });

  test('no re-read while the plan or the client page is open: the fixes stay as previewed', async () => {
    const env = await resultsWith([check([FIREFOX, SAMSUNG])]);
    env.ctl.toggleFix(SAMSUNG.all_fix!);
    // Firefox dostał zdalne debugowanie, a Samsung Internet nie oferuje już poprawki: odczyt zmieniłby plan.
    env.bridge.setChecks([check([{ ...FIREFOX, read: 'ok', rdp_hint: false }])]);
    env.s.plan = { apps: [], runnable: 1, code: 'K7F3' };
    await vi.advanceTimersByTimeAsync(15_000);
    expect(rechecks(env)).toBe(0);
    env.s.plan = null;
    env.s.share = { id: 'ui-1', code: 'K7F3', status: 'ready', url: 'https://x', mode: 'server', expires: null,
      upgraded: false, reason: null, offline: false };
    await vi.advanceTimersByTimeAsync(15_000);
    expect(rechecks(env)).toBe(0);
    expect([...env.s.fixes]).toEqual([SAMSUNG.all_fix]);
    env.s.share = null;
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(1);
    expect(env.s.fixes.size).toBe(0);
    env.view.unmount();
  });

  test('a failed re-read stays silent: no error card, the next one is tried', async () => {
    const env = await resultsWith([check([FIREFOX])]);
    env.bridge.failNext('recheck_site_notifications', 'busy');
    await vi.advanceTimersByTimeAsync(5000);
    expect(env.s.error).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(2);
    env.view.unmount();
  });
});
