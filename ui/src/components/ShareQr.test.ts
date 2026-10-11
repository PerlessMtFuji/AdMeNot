import { fireEvent, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
import vector from '../../../tests/fixtures/share_vector.json';
import { renderWith } from '../test-utils';
import ShareQr from './ShareQr.svelte';

describe('ShareQr', () => {
  it('shows the button, then the QR, the code and the consent box', async () => {
    const { s } = await renderWith(ShareQr, 'adware');
    s.plan = { apps: [], runnable: 1, code: 'K7F3' };
    expect(screen.queryByRole('checkbox')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /Pokaż klientowi/ }));
    // Atrapa wysyła `share:ready` w łańcuchu zdarzeń po wyniku wywołania: czekamy, aż dotrze.
    expect(await screen.findByRole('img', { name: /Kod QR/ })).toBeTruthy();
    expect(screen.getByText('K7F3')).toBeTruthy();
    const box = screen.getByRole('checkbox', { name: /zapoznał się/ });
    await fireEvent.click(box);
    expect(s.consent).toBe(true);
  });

  it('local mode warns, too_long shows no QR and no consent', async () => {
    const { s, bridge } = await renderWith(ShareQr, 'adware');
    s.share = { id: 'a', code: 'K7F3', status: 'sending', url: null, mode: null, expires: null, upgraded: false, reason: null };
    bridge.emit('share:ready', { share_id: 'a', code: 'K7F3', url: 'https://x/plan#l.q', mode: 'local', expires: null });
    await tick();
    expect(screen.getByText(/Kod działa bez ikon/)).toBeTruthy();
    s.share = { id: 'b', code: 'K7F3', status: 'sending', url: null, mode: null, expires: null, upgraded: false, reason: null };
    bridge.emit('share:failed', { share_id: 'b', code: 'K7F3', reason: 'too_long' });
    await tick();
    expect(screen.getByText(/za długi/)).toBeTruthy();
    expect(screen.queryByRole('img', { name: /Kod QR/ })).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('plan_changed notice is visible', async () => {
    const { s } = await renderWith(ShareQr, 'adware');
    s.planChanged = true;
    await tick();
    expect(screen.getByText(/Pokaż klientowi nowy kod/)).toBeTruthy();
  });
});

// Kod musi dać się zeskanować telefonem: co najmniej 3 px ekranu na moduł (przegląd 2026-10-11).
// Adres na granicy limitu trybu lokalnego (engine/share.py LOCAL_LIMIT) z adresem produkcyjnym.
const MIN_PX = 3;
const longUrl = 'https://admenot.e-wlodarski.workers.dev/plan#l.' + 'x'.repeat(vector.local_limit - 2);
const pxPerModule = (svg: Element) => Number(svg.getAttribute('width')) / Number(svg.getAttribute('viewBox')!.split(' ')[2]);

describe('ShareQr readability', () => {
  it('a server-mode code is drawn inline at 3 px per module or more, without the zoom button', async () => {
    const { s, bridge } = await renderWith(ShareQr, 'adware');
    s.share = { id: 'a', code: 'K7F3', status: 'sending', url: null, mode: null, expires: null, upgraded: false, reason: null };
    bridge.emit('share:ready', { share_id: 'a', code: 'K7F3', mode: 'server', expires: null,
      url: `https://admenot.e-wlodarski.workers.dev/plan#s.${'A'.repeat(22)}.${'B'.repeat(43)}` });
    await tick();
    expect(pxPerModule(screen.getByRole('img', { name: /Kod QR/ }))).toBeGreaterThanOrEqual(MIN_PX);
    expect(screen.queryByRole('button', { name: /Powiększ kod/ })).toBeNull();
  });

  it('a local code at the length limit can be enlarged to 3 px per module inside the dialog', async () => {
    const { s, bridge } = await renderWith(ShareQr, 'adware');
    s.share = { id: 'b', code: 'K7F3', status: 'sending', url: null, mode: null, expires: null, upgraded: false, reason: null };
    bridge.emit('share:ready', { share_id: 'b', code: 'K7F3', url: longUrl, mode: 'local', expires: null });
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: /Powiększ kod/ }));
    const dialog = screen.getByRole('dialog');
    const big = within(dialog).getByRole('img', { name: /Kod QR/ });
    expect(pxPerModule(big)).toBeGreaterThanOrEqual(MIN_PX);
    expect(Number(big.getAttribute('width'))).toBeLessThanOrEqual(440); // treść okna: 500 px − marginesy
  });
});
