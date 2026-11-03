import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, onTestFinished, test, vi } from 'vitest';
import { renderWith, setupCtl } from '../test-utils';
import Connect from './Connect.svelte';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('Connect', () => {
  test('phone cleanup running: a warning, scan and transfer disabled, the role prompt shown; a failure stays one banner', async () => {
    const env = await setupCtl('clean');
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    env.s.serial = 'R58T00TEST';
    env.s.transfer.cleanup = { serial: 'R58T00TEST', running: true, ok: null };
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    expect(screen.getByText('Przywracam ustawienia telefonu po przerwanym wgrywaniu…')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Kopiuj dane' }) as HTMLButtonElement).disabled).toBe(true);
    env.bridge.emit('transfer:tap', { request: 'sms_role_restore', package: 'com.samsung.android.messaging' });
    await tick();
    expect(screen.getByText('Na telefonie: wybierz Wiadomości Samsung jako domyślną aplikację SMS')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Pomiń/ })).toBeNull();
    env.bridge.emit('transfer:cleanup_done', { ok: false, serial: 'R58T00TEST' });
    env.bridge.emit('transfer:cleanup_started', { serial: 'R58T00TEST' });  // ponowienie w tle
    await tick();
    expect(screen.getAllByText('Telefon nie wrócił do swoich ustawień')).toHaveLength(1);
    expect(screen.queryByText(/Przywracam ustawienia/)).toBeNull();  // bez migania na żółto
    env.bridge.emit('transfer:cleanup_done', { ok: false, serial: 'R58T00TEST' });
    await tick();
    expect(screen.getAllByText('Telefon nie wrócił do swoich ustawień')).toHaveLength(1);
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(false);
  });

  test('no phone: title, waiting stage, open guide with maker tabs, no scan button', async () => {
    const { container } = await renderWith(Connect, 'empty');
    expect(screen.getByRole('heading', { name: 'Podłącz telefon' })).toBeTruthy();
    expect(container.querySelector('[data-state="wait"]')).toBeTruthy();
    const checks = screen.getByRole('list', { name: 'Stan połączenia' }).querySelectorAll('li');
    expect([...checks].map((li) => li.dataset.status)).toEqual(['on', 'todo', 'todo']);
    await fireEvent.click(screen.getByRole('button', { name: 'Xiaomi / Redmi / POCO' }));
    expect(screen.getByText('Debugowanie USB (ustawienia zabezpieczeń)')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Skanuj' })).toBeNull();
  });

  test('a ready phone shows its marketing name and IMEI, not the model code and serial', async () => {
    const env = await setupCtl('clean');
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: 'Samsung Galaxy A14', imei: '499001200000004' }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    expect(screen.getByText('Samsung Galaxy A14')).toBeTruthy();
    expect(screen.getByText('IMEI 499001200000004')).toBeTruthy();
    expect(screen.queryByText('R58T00TEST')).toBeNull();
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    await tick();
    expect(screen.getByText('SM A145R')).toBeTruthy();
    expect(screen.getByText('R58T00TEST')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Kopiuj IMEI' })).toBeNull();  // bez IMEI nie ma czego kopiować
  });

  test('the IMEI of a ready phone can be copied to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    onTestFinished(() => { vi.unstubAllGlobals(); });
    const env = await setupCtl('clean');
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: 'Samsung Galaxy A14', imei: '499001200000004' }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Kopiuj IMEI' }));
    await flush();
    expect(writeText).toHaveBeenCalledWith('499001200000004');  // same cyfry, bez „IMEI ”
    expect(screen.getByRole('status').textContent).toBe('Skopiowano IMEI');
  });

  test('several phones: copying an IMEI from a row does not change the selected phone', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    onTestFinished(() => { vi.unstubAllGlobals(); });
    const { s } = await renderWith(Connect, 'many');
    s.devices = [
      { serial: 'A1', state: 'device', model: 'CPH2271', name: 'Oppo A16s', imei: '861580056585051', android: '12' },
      { serial: 'B2', state: 'device', model: '22101316G', name: 'Xiaomi Redmi Note 12 Pro', imei: '861485069821024', android: '13' },
    ];
    s.serial = 'A1';
    await tick();
    const rows = (screen.getAllByRole('radio') as HTMLInputElement[]).map((r) => r.closest('label')!);
    await fireEvent.click(within(rows[1]).getByRole('button', { name: 'Kopiuj IMEI' }));
    await flush();
    expect(writeText).toHaveBeenCalledWith('861485069821024');
    expect(s.serial).toBe('A1');
  });

  test('a phone with an interrupted data copy is offered resuming it right after connecting', async () => {
    const env = await setupCtl('clean');
    const copy = { id: 'R58T00TEST-x/20261025-193539', serial: 'R58T00TEST', model: 'SM-A145R', manufacturer: 'samsung',
      client: null, created: '2026-10-25T19:35:39', expires: '2026-11-01T19:35:39', days_left: 7,
      status: 'in_progress' as const, bytes: 0, counts: {} };
    env.bridge.setCopies([{ ...copy, id: 'OTHER/1', serial: 'OTHER' }]);
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await flush();
    expect(screen.queryByText(/Wznów przerwaną kopię/)).toBeNull();  // kopia innego egzemplarza
    env.bridge.setCopies([copy]);
    await env.ctl.loadTransfers();
    await tick();
    expect(screen.getByText(/Wznów przerwaną kopię z 25 paź/)).toBeTruthy();
    const start = vi.spyOn(env.ctl, 'startTransfer');
    await fireEvent.click(screen.getByRole('button', { name: 'Wznów' }));
    expect(start).toHaveBeenCalledWith(true);  // wznowienie, nie nowy wybór danych
  });

  test('a new phone is offered the newest copy of another phone; "Upload" plans it, "Another copy" opens the list', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-25T20:35:39'));  // kopia sprzed godziny: świeża
    onTestFinished(() => { vi.useRealTimers(); });
    const env = await setupCtl('clean');
    const copy = { id: 'OLD/20261025-193539', serial: 'OLD', model: 'SM-A145R', manufacturer: 'samsung', client: 'Anna K.',
      created: '2026-10-25T19:35:39', expires: '2026-11-01T19:35:39', days_left: 7, status: 'complete' as const, bytes: 10,
      counts: {}, restores: [] };
    env.bridge.setCopies([copy]);
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await flush();
    expect(screen.getByText(/Wgrać kopię z samsung SM-A145R \(Anna K\., 25 paź/)).toBeTruthy();
    const plan = vi.spyOn(env.ctl, 'planRestore').mockResolvedValue();
    await fireEvent.click(screen.getByRole('button', { name: 'Wgraj' }));
    expect(plan).toHaveBeenCalledWith(copy.id);
    const history = vi.spyOn(env.ctl, 'openHistory').mockResolvedValue();
    await fireEvent.click(screen.getByRole('button', { name: 'Inna kopia' }));
    expect(history).toHaveBeenCalled();
  });

  test('any finished copy can be uploaded by hand, also an old one already uploaded to this phone', async () => {
    const env = await setupCtl('clean');
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await flush();
    expect(screen.queryByRole('button', { name: 'Wgraj kopię' })).toBeNull();  // nie ma czego wgrać
    const copy = { id: 'OLD/20261020-100000', serial: 'OLD', model: 'SM-A145R', manufacturer: 'samsung', client: null,
      created: '2026-10-20T10:00:00', expires: '2026-10-27T10:00:00', days_left: 1, status: 'complete' as const, bytes: 10,
      counts: {}, restores: [{ serial: 'R58T00TEST', status: 'complete', updated: null, resumable: false }] };
    env.bridge.setCopies([copy]);
    await env.ctl.loadTransfers();
    await tick();
    expect(screen.queryByText(/Wgrać kopię/)).toBeNull();  // stara i już wgrana: bez banera
    const history = vi.spyOn(env.ctl, 'openHistory').mockResolvedValue();
    await fireEvent.click(screen.getByRole('button', { name: 'Wgraj kopię' }));
    expect(history).toHaveBeenCalled();
  });

  test('an interrupted upload to this phone is offered for resuming instead of a new upload', async () => {
    const env = await setupCtl('clean');
    const copy = { id: 'OLD/1', serial: 'OLD', model: 'SM-A145R', manufacturer: 'samsung', client: null,
      created: '2026-10-25T19:35:39', expires: '2026-11-01T19:35:39', days_left: 7, status: 'complete' as const, bytes: 10,
      counts: {}, restores: [{ serial: 'R58T00TEST', status: 'stopped', updated: null, resumable: true }] };
    env.bridge.setCopies([copy]);
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await flush();
    expect(screen.getByText('Wznów przerwane wgrywanie')).toBeTruthy();
    expect(screen.queryByText(/Wgrać kopię/)).toBeNull();
    const plan = vi.spyOn(env.ctl, 'planRestore').mockResolvedValue();
    await fireEvent.click(screen.getByRole('button', { name: 'Wznów' }));
    expect(plan).toHaveBeenCalledWith('OLD/1');
    // przerwana kopia tego telefonu (Etap 1) ma pierwszeństwo
    env.bridge.setCopies([copy, { ...copy, id: 'R58T00TEST-x/1', serial: 'R58T00TEST', status: 'in_progress', restores: [] }]);
    await env.ctl.loadTransfers();
    await tick();
    expect(screen.getByText(/Wznów przerwaną kopię/)).toBeTruthy();
    expect(screen.queryByText('Wznów przerwane wgrywanie')).toBeNull();
  });

  test('the connect screen reloads the copies, so a finished copy no longer offers resuming', async () => {
    const env = await setupCtl('clean');
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await flush();
    expect(env.bridge.calls.some((c) => c.method === 'transfers')).toBe(true);
  });

  test('unauthorized phone asks for the permission on the phone', async () => {
    const { container } = await renderWith(Connect, 'unauthorized');
    expect(screen.getByRole('heading', { name: 'Potwierdź na telefonie' })).toBeTruthy();
    expect(container.querySelector('[data-state="auth"]')).toBeTruthy();
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
  });

  test('a phone scanned before starts with the guide collapsed', async () => {
    const env = await setupCtl('unauthorized');
    env.s.knownSerials = ['R58T00TEST'];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    expect(screen.queryByText('Jak włączyć debugowanie USB')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Pokaż, jak włączyć debugowanie USB' }));
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
  });

  test('the guide collapses once the phone turns out to be known (history arrives after the first render)', async () => {
    const env = await setupCtl('unauthorized');
    env.s.knownSerials = [];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
    env.s.knownSerials = ['R58T00TEST'];
    await tick();
    expect(screen.queryByText('Jak włączyć debugowanie USB')).toBeNull();
    expect(screen.getByRole('button', { name: 'Pokaż, jak włączyć debugowanie USB' })).toBeTruthy();
  });

  test('several phones: pick one, then scan', async () => {
    const { s, bridge } = await renderWith(Connect, 'many');
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(2);
    await fireEvent.click(radios[1]);
    expect(s.serial).toBe('HT7A1B2C3');
    await fireEvent.input(screen.getByPlaceholderText('np. Anna K.'), { target: { value: 'Jan' } });
    expect(s.client).toBe('Jan');
    await fireEvent.click(screen.getByRole('button', { name: 'Skanuj' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'start_scan', args: ['HT7A1B2C3', 'Jan'] });
  });

  test('several phones: one set of screen tools, for the selected phone', async () => {
    const { s, bridge } = await renderWith(Connect, 'many');
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    await fireEvent.click(radios[1]);
    await tick();
    const shot = screen.getByRole('button', { name: 'Zrzut ekranu' });  // jeden, nie po jednym na telefon
    // Przyciski podglądu/zrzutu nie mogą być potomkami <label> (klik trafiałby do radia).
    expect(shot.closest('label')).toBeNull();
    const tools = shot.closest('section')!;
    expect(tools.getAttribute('aria-label')).toBe('samsung SM-A145R HT7A1B2C3');
    await fireEvent.click(shot);
    await flush();
    await tick();
    expect(bridge.calls.at(-1)).toEqual({ method: 'screenshot', args: ['HT7A1B2C3'] });
    expect(s.serial).toBe('HT7A1B2C3');
    expect(radios.map((r) => r.checked)).toEqual([false, true]);
    expect(within(radios[1].closest('label')!).getByText('wybrany')).toBeTruthy();
  });

  test('several phones: rows and the tools bar name each phone by IMEI, the serial only as a fallback', async () => {
    const { s } = await renderWith(Connect, 'many');
    s.devices = [
      { serial: '79SSSW6PDMEMCI6S', state: 'device', model: 'CPH2271', name: 'Oppo A16s', imei: '861580056585051', android: '12' },
      { serial: 'nz7pukyxcu8t4d6l', state: 'device', model: '22101316G', name: 'Xiaomi Redmi Note 12 Pro', imei: null, android: '13' },
    ];
    s.serial = '79SSSW6PDMEMCI6S';
    await tick();
    const [oppo, xiaomi] = (screen.getAllByRole('radio') as HTMLInputElement[]).map((r) => r.closest('label')!);
    expect(within(oppo).getByText('IMEI 861580056585051').getAttribute('title')).toBe('S/N: 79SSSW6PDMEMCI6S');
    expect(within(oppo).getByText('Android 12')).toBeTruthy();
    expect(oppo.textContent).not.toContain('79SSSW6PDMEMCI6S');
    expect(within(xiaomi).getByText('nz7pukyxcu8t4d6l')).toBeTruthy();  // bez IMEI: numer seryjny
    const tools = screen.getByRole('button', { name: 'Zrzut ekranu' }).closest('section')!;
    expect(tools.getAttribute('aria-label')).toBe('Oppo A16s IMEI 861580056585051');
    expect(within(tools).getByText('IMEI 861580056585051')).toBeTruthy();
    expect(tools.textContent).not.toContain('79SSSW6PDMEMCI6S');
  });

  test('several phones, none picked: no tools, scan disabled, a hint says to pick one', async () => {
    const { s } = await renderWith(Connect, 'many');
    s.serial = null;
    await tick();
    expect(screen.queryByRole('button', { name: 'Zrzut ekranu' })).toBeNull();
    expect(screen.getByText(/^Wybierz telefon z listy/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getAllByRole('radio')[0]);
    expect(screen.queryByText(/^Wybierz telefon z listy/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Zrzut ekranu' })).toBeTruthy();
  });

  test('several phones: a screen view running on the other phone is marked in its row', async () => {
    const { s } = await renderWith(Connect, 'many');
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    await fireEvent.click(radios[0]);
    s.mirror.serial = 'HT7A1B2C3';
    s.mirror.state = 'running';
    await tick();
    expect(within(radios[1].closest('label')!).getByText('podgląd włączony')).toBeTruthy();
    expect(within(radios[0].closest('label')!).queryByText('podgląd włączony')).toBeNull();
  });

  test('"Files" opens the explorer of the selected phone', async () => {
    const env = await setupCtl('explorer');
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    const files = screen.getByRole('button', { name: 'Pliki' }) as HTMLButtonElement;
    expect(files.disabled).toBe(false);
    await fireEvent.click(files);
    await vi.waitFor(() => expect(env.s.screen).toBe('explorer'));
    expect(env.bridge.calls.find((c) => c.method === 'explorer_open')?.args).toEqual(['R58T00TEST']);
    expect(env.ctl.explorer.state.open).toBe(true);
  });

  test('"Files" is disabled with a reason while a task runs, during phone cleanup and with no phone picked', async () => {
    const env = await setupCtl('many');
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    const files = () => screen.getByRole('button', { name: 'Pliki' }) as HTMLButtonElement;
    env.s.serial = null;
    await tick();
    expect(files().disabled).toBe(true);
    expect(files().title).toBe('Najpierw wybierz telefon z listy');
    env.s.serial = 'HT7A1B2C3';
    env.s.job = { id: 'job-1', kind: 'scan' };
    await tick();
    expect(files().disabled).toBe(true);
    expect(files().title).toBe('Dostępne po zakończeniu bieżącego zadania');
    env.s.job = null;
    env.s.transfer.cleanup = { serial: 'HT7A1B2C3', running: true, ok: null };
    await tick();
    expect(files().disabled).toBe(true);
    expect(files().title).toBe('Dostępne po przywróceniu ustawień telefonu');
    env.s.transfer.cleanup = { serial: null, running: false, ok: null };
    await tick();
    expect(files().disabled).toBe(false);
    expect(files().title).toBe('');
  });

  test('a busy phone: the bridge refuses "Files", a banner explains it and the screen stays', async () => {
    const env = await setupCtl('explorer');
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    env.bridge.failNext('explorer_open', 'explorer_busy', 'device');
    await fireEvent.click(screen.getByRole('button', { name: 'Pliki' }));
    await vi.waitFor(() => expect(screen.getByText(/Na tym telefonie trwa inna operacja/)).toBeTruthy());
    expect(env.s.screen).toBe('main');
    expect(env.s.error).toBeNull();  // baner na „Połącz”, nie karta błędu
    await fireEvent.click(screen.getByRole('button', { name: 'Pliki' }));  // druga próba: baner znika
    await vi.waitFor(() => expect(env.s.screen).toBe('explorer'));
    expect(screen.queryByText(/Na tym telefonie trwa inna operacja/)).toBeNull();
  });

  test('one ready phone: connected card with scan; adb missing points to settings', async () => {
    const { s, container } = await renderWith(Connect, 'adware');
    expect(screen.getByRole('heading', { name: 'Połączono' })).toBeTruthy();
    expect(container.querySelector('[data-state="ok"]')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(false);
    s.devicesError = 'adb_missing';
    s.devices = [];
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Otwórz ustawienia' }));
    expect(s.screen).toBe('settings');
  });
});
