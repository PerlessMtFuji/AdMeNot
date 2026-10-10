import { fireEvent, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import Welcome from './Welcome.svelte';

describe('Welcome', () => {
  test('„Zaczynamy” jest nieaktywny bez akceptacji', async () => {
    const { bridge } = await renderWith(Welcome, 'empty', {}, { welcome: true });
    const start = screen.getByRole('button', { name: 'Zaczynamy' });
    expect((start as HTMLInputElement).disabled).toBe(true);
    await fireEvent.click(screen.getByLabelText('Rozumiem i akceptuję'));
    expect((start as HTMLInputElement).disabled).toBe(false);
    await fireEvent.click(start);
    await waitFor(() => expect(bridge.calls.some((c) => c.method === 'accept_welcome')).toBe(true));
    expect(bridge.calls.find((c) => c.method === 'accept_welcome')!.args).toEqual([false, false]);
  });

  test('nazwy pakietów zależą od statystyk', async () => {
    await renderWith(Welcome, 'empty', {}, { welcome: true });
    const telemetry = screen.getByLabelText(/Wysyłaj anonimowe statystyki użycia/);
    const packages = screen.getByLabelText(/Dołącz nazwy pakietów oznaczonych i usuwanych aplikacji/);
    expect((packages as HTMLInputElement).disabled).toBe(true);
    await fireEvent.click(telemetry);
    expect((packages as HTMLInputElement).disabled).toBe(false);
    await fireEvent.click(packages);
    expect((packages as HTMLInputElement).checked).toBe(true);
    await fireEvent.click(telemetry);
    expect((packages as HTMLInputElement).disabled).toBe(true);
    expect((packages as HTMLInputElement).checked).toBe(false);
  });

  test('przełącznik języka zmienia teksty', async () => {
    await renderWith(Welcome, 'empty', {}, { welcome: true });
    await fireEvent.click(screen.getByRole('button', { name: 'English' }));
    await screen.findByRole('button', { name: 'Get started' });
  });

  test('błąd zapisu zostaje na ekranie powitalnym', async () => {
    const { bridge } = await renderWith(Welcome, 'empty', {}, { welcome: true });
    bridge.failNext('accept_welcome', 'data_too_new');
    await fireEvent.click(screen.getByLabelText('Rozumiem i akceptuję'));
    await fireEvent.click(screen.getByRole('button', { name: 'Zaczynamy' }));
    await screen.findByRole('alert');
    expect((screen.getByRole("button", { name: "Zaczynamy" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
