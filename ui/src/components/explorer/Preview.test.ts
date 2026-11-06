import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import App from '../../App.svelte';
import { setupCtl } from '../../test-utils';
import type { EntryView } from '../../lib/types';

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: () => ({ promise: new Promise(() => {}), destroy: async () => {} }),
}));

const GPS_FILE = '/sdcard/DCIM/Camera/IMG_20260926_0000.jpg';
const NOTE = '/sdcard/Download/notatka.txt';

const entry = (name: string, type: EntryView['type'], ext: string): EntryView => ({
  name, path: `/sdcard/Download/${name}`, kind: 'file', size: 4096, mtime: 1790413200, label: null, locked: false,
  type, ext, thumb: null, url: `http://127.0.0.1:0/TOKEN/file?p=${encodeURIComponent(name)}`,
});

/** Eksplorator otwarty na zdjęciach z Aparatu; dodatkowo w tym folderze leżą utwór i zdjęcie HEIC. */
async function openExplorer() {
  const env = await setupCtl('explorer');
  render(App, { props: { ctl: env.ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Pliki' }));
  await vi.waitFor(() => expect(screen.getByRole('listbox', { name: 'Pliki w folderze' })).toBeTruthy());
  const ex = env.ctl.explorer;
  ex.state.entries = [...ex.state.entries, entry('piosenka.mp3', 'audio', 'mp3'), entry('druga.mp3', 'audio', 'mp3'), entry('IMG_0001.heic', 'image', 'heic')];
  return { ...env, ex };
}

const dialog = () => screen.getByRole('dialog');

describe('Preview', () => {
  test('text search highlights literal matches and moves between them', async () => {
    const { ex, bridge } = await openExplorer();
    await ex.go('/sdcard/Download');
    bridge.answerNext('explorer_text', { text: 'Żółć żółci żółć <script>', encoding: 'utf-8', truncated: false });
    ex.openPreview(NOTE);
    const input = await screen.findByRole('searchbox', { name: 'Szukaj w treści' });
    await fireEvent.input(input, { target: { value: 'żół' } });
    expect(dialog().querySelectorAll('mark')).toHaveLength(3);
    await fireEvent.click(screen.getByRole('checkbox', { name: 'Całe wyrazy' }));
    expect(dialog().querySelectorAll('mark')).toHaveLength(0);
    await fireEvent.input(input, { target: { value: 'żółć' } });
    expect(dialog().querySelectorAll('mark')).toHaveLength(2);
    await fireEvent.click(screen.getByRole('button', { name: 'Następne trafienie' }));
    expect(dialog().querySelector('mark.active')?.getAttribute('data-hit')).toBe('1');
    expect(dialog().querySelector('script')).toBeNull();
    await fireEvent.keyDown(input, { key: 'Escape' });
    expect(ex.state.preview).toBe(NOTE);
  });

  test('full text search loads the remaining chunks and updates the match count', async () => {
    const { ex, bridge } = await openExplorer();
    await ex.go('/sdcard/Download');
    bridge.answerNext('explorer_text', { text: 'first needle', encoding: 'utf-8', truncated: true });
    ex.openPreview(NOTE);
    const input = await screen.findByRole('searchbox', { name: 'Szukaj w treści' });
    await fireEvent.input(input, { target: { value: 'needle' } });
    await vi.waitFor(() => expect(dialog().querySelectorAll('mark')).toHaveLength(1));
    expect(dialog().textContent).toContain('Szukanie obejmuje wczytaną część');
    bridge.answerNext('explorer_text', { text: ' second needle', encoding: 'utf-8', truncated: false });
    await fireEvent.click(screen.getByRole('button', { name: 'Wczytaj całość' }));
    await vi.waitFor(() => expect(dialog().querySelectorAll('mark')).toHaveLength(2));
    expect(dialog().textContent).not.toContain('Szukanie obejmuje wczytaną część');
  });

  test('PDF opens the isolated reader instead of unsupported-file view', async () => {
    const { ex } = await openExplorer();
    const pdf = entry('dokument.pdf', 'doc', 'pdf');
    ex.state.entries.push(pdf);
    ex.openPreview(pdf.path);
    await tick();
    expect(within(dialog()).getByRole('searchbox', { name: 'Szukaj w treści' })).toBeTruthy();
    expect(dialog().querySelector('canvas')?.getAttribute('aria-label')).toBe('Podgląd PDF');
  });

  test('video dimensions decoded by the player fill in an empty MediaStore reply', async () => {
    const { ex, bridge } = await openExplorer();
    const movie = entry('pionowy.mp4', 'video', 'mp4');
    ex.state.entries = [...ex.state.entries, movie];
    bridge.answerNext('explorer_meta', { meta: { path: movie.path, size: movie.size, mtime: movie.mtime } });
    ex.openPreview(movie.path);
    await tick();
    const video = dialog().querySelector('video')!;
    Object.defineProperties(video, {
      videoWidth: { value: 1080 }, videoHeight: { value: 1920 }, duration: { value: 12 },
    });
    await fireEvent.loadedMetadata(video);
    await fireEvent.click(screen.getByRole('button', { name: 'Informacje o pliku' }));
    const panel = screen.getByRole('complementary', { name: 'Informacje o pliku' });
    expect(panel.textContent).toContain('1080 × 1920');
    expect(within(panel).getByText('MP4')).toBeTruthy();
    expect(dialog().querySelector('header')?.textContent).toContain('1080 × 1920');
  });

  test('arrow keys move only through the files visible after the filter; Esc closes', async () => {
    const { ex } = await openExplorer();
    ex.setQuery('20260926_001');
    const shown = ex.items.filter((e) => e.kind === 'file').map((e) => e.path);
    expect(shown.length).toBeGreaterThan(3);
    ex.openPreview(shown[0]);
    await tick();
    expect(dialog().getAttribute('aria-label')).toContain(shown[0].split('/').pop()!);

    const visited = [ex.state.preview];
    for (let i = 0; i < shown.length + 2; i++) {
      await fireEvent.keyDown(window, { key: 'ArrowRight' });
      visited.push(ex.state.preview);
    }
    expect(visited.slice(0, shown.length)).toEqual(shown);
    expect(ex.state.preview).toBe(shown.at(-1));  // koniec listy: bez zawijania, bez wyjścia poza filtr

    await fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(ex.state.preview).toBe(shown.at(-2));

    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(ex.state.preview).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('a double click on a tile opens the preview of that file', async () => {
    const { ex } = await openExplorer();
    const tile = within(screen.getByRole('listbox', { name: 'Pliki w folderze' })).getAllByRole('option')[0];
    await fireEvent.dblClick(tile);
    expect(ex.state.preview).toBe(tile.getAttribute('data-path'));
    expect(dialog()).toBeTruthy();
  });

  test('the info panel shows exact GPS and "Show on map" opens it', async () => {
    const { ex, bridge } = await openExplorer();
    ex.openPreview(GPS_FILE);
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Informacje o pliku' }));
    const panel = await screen.findByRole('complementary', { name: 'Informacje o pliku' });
    await vi.waitFor(() => expect(panel.textContent).toContain('52.229778, 21.011694'));
    expect(within(panel).getByText('Lokalizacja')).toBeTruthy();
    expect(within(panel).getByText('Producent')).toBeTruthy();  // Make = OPPO
    expect(panel.textContent).toContain('OPPO');
    await fireEvent.click(within(panel).getByRole('button', { name: 'Pokaż na mapie' }));
    expect(bridge.calls.find((c) => c.method === 'explorer_open_map')?.args).toEqual([52.229778, 21.011694]);
  });

  test('a cp1250 text file shows its encoding and "Show more" appends the next chunk', async () => {
    const { ex, bridge } = await openExplorer();
    await ex.go('/sdcard/Download');
    ex.openPreview(NOTE);
    await tick();
    await vi.waitFor(() => expect(dialog().textContent).toContain('Zażółć gęślą jaźń'));
    expect(dialog().textContent).toContain('cp1250');
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Pokaż więcej' }));
    await vi.waitFor(() => expect(dialog().textContent).toContain('Dalszy ciąg'));
    expect(dialog().textContent).toContain('Zażółć gęślą jaźń');  // pierwszy kawałek zostaje
    expect(within(dialog()).queryByRole('button', { name: 'Pokaż więcej' })).toBeNull();
    expect(bridge.calls.filter((c) => c.method === 'explorer_text').map((c) => c.args)).toEqual([[NOTE, false], [NOTE, true]]);
  });

  test('closing the preview while music plays leaves the mini player; its X stops it', async () => {
    const { ex } = await openExplorer();
    const song = ex.state.entries.find((e) => e.type === 'audio')!;
    ex.openPreview(song.path);
    await tick();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Odtwórz' }));
    expect(ex.state.playing).toMatchObject({ path: song.path, title: 'piosenka.mp3' });
    expect(ex.audio.el.play).toHaveBeenCalled();

    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    const mini = screen.getByRole('region', { name: 'Mini odtwarzacz' });
    expect(mini.textContent).toContain('piosenka.mp3');

    await fireEvent.click(within(mini).getByRole('button', { name: 'Zatrzymaj i zamknij' }));
    expect(screen.queryByRole('region', { name: 'Mini odtwarzacz' })).toBeNull();
    expect(ex.state.playing).toBeNull();
  });

  test('Space pauses and resumes the track', async () => {
    const { ex } = await openExplorer();
    const song = ex.state.entries.find((e) => e.type === 'audio')!;
    ex.openPreview(song.path);
    await tick();
    await fireEvent.keyDown(window, { key: ' ' });
    expect(ex.state.playing?.path).toBe(song.path);
    Object.defineProperty(ex.audio.el, 'paused', { value: false, configurable: true });
    await fireEvent.keyDown(window, { key: ' ' });
    expect(ex.audio.el.pause).toHaveBeenCalled();
  });

  test('HEIC is not shown in <img>: big icon, metadata and "Copy to computer" copy just this file', async () => {
    const { ex, bridge } = await openExplorer();
    const heic = ex.state.entries.find((e) => e.ext === 'heic')!;
    ex.openPreview(heic.path);
    await tick();
    expect(dialog().querySelector('img[src*="TOKEN/file"]')).toBeNull();
    expect(within(dialog()).getByText('Tego pliku nie da się tu pokazać', { exact: false })).toBeTruthy();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Kopiuj na komputer' }));
    await vi.waitFor(() => expect(bridge.calls.find((c) => c.method === 'explorer_copy')).toBeTruthy());
    expect(bridge.calls.find((c) => c.method === 'explorer_copy')?.args[0]).toEqual([heic.path]);
  });

  test('a failed copy started from the preview shows a Banner inside the preview', async () => {
    const { ex, bridge } = await openExplorer();
    ex.openPreview(GPS_FILE);
    await tick();
    bridge.failNext('explorer_copy', 'explorer_offline');
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Kopiuj na komputer' }));
    const alert = await within(dialog()).findByRole('alert');
    expect(alert.textContent).toContain('Telefon nie odpowiada');
    await fireEvent.click(within(alert).getByRole('button', { name: 'Zamknij' }));
    expect(within(dialog()).queryByRole('alert')).toBeNull();
  });

  test('a started copy is confirmed inside the preview', async () => {
    const { ex } = await openExplorer();
    ex.openPreview(GPS_FILE);
    await tick();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Kopiuj na komputer' }));
    const status = await within(dialog()).findByText('Kopiowanie rozpoczęte', { exact: false });
    expect(status).toBeTruthy();
    expect(within(dialog()).queryByRole('alert')).toBeNull();
  });

  test('the next-track button and auto-advance follow the playlist captured at start, even after browsing away', async () => {
    const { ex } = await openExplorer();
    const [first, second] = ['druga.mp3', 'piosenka.mp3'].map((n) => ex.state.entries.find((e) => e.name === n)!);
    ex.openPreview(first.path);
    await tick();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Odtwórz' }));
    await fireEvent.keyDown(window, { key: 'Escape' });
    await ex.go('/sdcard/Download');  // inny folder: druga.mp3 i piosenka.mp3 nie ma już na liście
    expect(ex.items.some((e) => e.type === 'audio')).toBe(false);
    const mini = screen.getByRole('region', { name: 'Mini odtwarzacz' });
    await fireEvent.click(within(mini).getByRole('button', { name: 'Następny utwór' }));
    expect(ex.state.playing?.path).toBe(second.path);
    expect(within(screen.getByRole('region', { name: 'Mini odtwarzacz' })).getByRole('button', { name: 'Następny utwór' })
      .hasAttribute('disabled')).toBe(true);  // ostatni na liście

    ex.stopTrack();
    ex.state.entries = [...ex.state.entries, first, second];
    await ex.playTrack(first);
    ex.audio.el.dispatchEvent(new Event('ended'));
    await vi.waitFor(() => expect(ex.state.playing?.path).toBe(second.path));
  });

  test('an audio error shows a Banner in the preview and an error state in the mini player', async () => {
    const { ex } = await openExplorer();
    const song = ex.state.entries.find((e) => e.name === 'piosenka.mp3')!;
    ex.openPreview(song.path);
    await tick();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Odtwórz' }));
    ex.audio.el.dispatchEvent(new Event('error'));
    expect((await within(dialog()).findByRole('alert')).textContent).toContain('Nie udało się odtworzyć tego utworu');
    await fireEvent.keyDown(window, { key: 'Escape' });
    const mini = screen.getByRole('region', { name: 'Mini odtwarzacz' });
    expect(within(mini).getByRole('alert').textContent).toContain('Nie udało się odtworzyć');
  });

  test('a successful replay of the same track clears the audio error', async () => {
    const { ex } = await openExplorer();
    const song = ex.state.entries.find((e) => e.name === 'piosenka.mp3')!;
    ex.openPreview(song.path);
    await tick();
    await fireEvent.click(within(dialog()).getByRole('button', { name: 'Odtwórz' }));
    ex.audio.el.dispatchEvent(new Event('error'));
    expect((await within(dialog()).findByRole('alert')).textContent).toContain('Nie udało się odtworzyć tego utworu');
    Object.defineProperty(ex.audio.el, 'paused', { value: true, configurable: true });
    await ex.toggleTrack(song);  // ten sam utwór jeszcze raz — tym razem gra
    expect(ex.state.playing?.path).toBe(song.path);
    expect(ex.state.playError).toBe(false);
    await vi.waitFor(() => expect(within(dialog()).queryByRole('alert')).toBeNull());
  });

  test('the preview closes when a refresh removes its file', async () => {
    const { ex, bridge } = await openExplorer();
    ex.openPreview(GPS_FILE);
    await tick();
    const s = ex.state;
    bridge.answerNext('explorer_list', JSON.parse(JSON.stringify({ path: s.path, crumbs: s.crumbs,
      entries: s.entries.filter((e) => e.path !== GPS_FILE), skipped: 0, locked: false })));
    await ex.refresh();
    await tick();
    expect(s.preview).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    await fireEvent.keyDown(window, { key: 'a', ctrlKey: true });  // skróty ekranu znów działają
    expect(s.selected.size).toBeGreaterThan(0);
  });
});
