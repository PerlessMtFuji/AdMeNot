import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';
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
