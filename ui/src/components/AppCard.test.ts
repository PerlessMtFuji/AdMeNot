import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import type { AppView, Finding } from '../lib/types';
import AppCard from './AppCard.svelte';

const finding = (rule_id: string, category: Finding['category'], label: string, weight: number) =>
  ({ rule_id, category, label, weight, class: '', text: '', text_expert: '', evidence: {}, basis: 'observed',
    source: 'phone', locations: [] }) as Finding;

const evil: AppView = {
  package: 'com.evil', name: '<img src=x onerror="alert(1)"> & „Cleaner”', score: 90,
  verdict: 'malicious', verdict_label: 'Szkodliwa', confidence: 'high', confidence_label: 'wysoka',
  gaps: [], scope: [], trusted: false, incomplete: false,
  is_system: false, from_play: false, installer: 'com.android.chrome', is_admin: true,
  default_level: 'remove', problems: [],
  findings: [finding('DM-ADMIN-01', 'removal', 'Administrator urządzenia', 25), finding('DM-OVERLAY-01', 'ads', 'Okna nad innymi aplikacjami', 20), finding('DM-SIDE-01', 'origin', 'Spoza Sklepu Play', 8)],
  capabilities: [], apk_error: null, icon: null, ad_sdks: null,
  symptoms: [{ category: 'ads', severity: 'bad', text: 'Pokazuje <b>reklamy</b>.' },
    { category: 'origin', severity: 'neutral', text: 'Spoza Play.' }],
  source: { label: 'Chrome', days: 3 },
};

test('app card: one compact line with two reasons, symptoms behind “Why?”', async () => {
  const onlevel = vi.fn();
  const ontoggle = vi.fn();
  const { container } = render(AppCard, { props: { app: evil, level: 'remove', onlevel, ontoggle } });
  expect(container.querySelector('img')).toBeNull();
  expect(screen.getByText('<img src=x onerror="alert(1)"> & „Cleaner”')).toBeTruthy();
  const reasons = screen.getByTestId('reasons');
  expect(reasons.textContent).toContain('Administrator urządzenia');
  expect(reasons.textContent).toContain('Okna nad innymi aplikacjami');
  expect(reasons.textContent).toContain('+1');
  // „+N” to osobny węzeł poza obciętą listą powodów, więc nie ginie przy długich etykietach
  const more = reasons.querySelector('[data-more]')!;
  expect(more.textContent).toContain('+1');
  expect(more.closest('.truncate')).toBeNull();
  expect(screen.queryByText('Szkodliwa')).toBeNull(); // werdykt mówi sekcja
  expect(screen.queryByText('Pokazuje <b>reklamy</b>.')).toBeNull();
  const why = screen.getByRole('button', { name: 'Dlaczego?' });
  expect(why.getAttribute('aria-expanded')).toBe('false');
  await fireEvent.click(why);
  expect(screen.getByText('Pokazuje <b>reklamy</b>.')).toBeTruthy();
  expect(container.querySelector('li b b')).toBeNull();
  expect(screen.getByText('com.evil')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Usuń' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(screen.getByRole('button', { name: 'Wyłącz' }));
  expect(onlevel).toHaveBeenCalledWith('disable');
  await fireEvent.click(screen.getByRole('checkbox', { name: evil.name }));
  expect(ontoggle).toHaveBeenCalledOnce();
  expect(container.textContent).not.toMatch(/DM-/);
});

test('app card: real icon from the APK, initial when it fails to load', async () => {
  const icon = 'data:image/png;base64,iVBORw0KGgo=';
  const props = { level: null, onlevel: vi.fn(), ontoggle: vi.fn() };
  const { container, rerender } = render(AppCard, { props: { ...props, app: { ...evil, icon } } });
  const initial = () => container.querySelector('span.text-white');
  const img = container.querySelector('img[data-app-icon]')!;
  expect(img.getAttribute('src')).toBe(icon);
  expect(img.getAttribute('alt')).toBe('');
  expect(initial()).toBeNull();
  await fireEvent.error(img);
  expect(container.querySelector('img[data-app-icon]')).toBeNull();
  expect(initial()?.textContent).toBe('<');
  await rerender({ ...props, app: { ...evil, icon: null } });
  expect(container.querySelector('img[data-app-icon]')).toBeNull();
  expect(initial()).not.toBeNull();
});

test('app card without findings names the symptom categories', () => {
  render(AppCard, { props: { app: { ...evil, findings: [] }, level: null, onlevel: vi.fn(), ontoggle: vi.fn() } });
  expect(screen.getByTestId('reasons').textContent).toContain('Reklamy');
});

test('app card: incomplete assessment is visible', () => {
  render(AppCard, { props: { app: { ...evil, incomplete: true }, level: null, onlevel: vi.fn(), ontoggle: vi.fn() } });
  expect(screen.getByText('Ocena niepełna')).toBeTruthy();
});
