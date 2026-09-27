import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import type { AppView } from '../lib/types';
import AppCard from './AppCard.svelte';

const evil: AppView = {
  package: 'com.evil', name: '<img src=x onerror="alert(1)"> & „Cleaner”', score: 90,
  verdict: 'malicious', verdict_label: 'Szkodliwa', trusted: false, incomplete: false,
  is_system: false, from_play: false, installer: 'com.android.chrome', is_admin: true,
  default_level: 'remove', problems: [], findings: [], apk_error: null, ad_sdks: null,
  symptoms: [{ category: 'ads', severity: 'bad', text: 'Pokazuje <b>reklamy</b>.' },
    { category: 'origin', severity: 'neutral', text: 'Spoza Play.' }],
  source: { label: 'Chrome', days: 3 },
};

test('app card: literal labels, symptom rows, action switch and checkbox', async () => {
  const onlevel = vi.fn();
  const ontoggle = vi.fn();
  const { container } = render(AppCard, { props: { app: evil, level: 'remove', onlevel, ontoggle } });
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('li b b')).toBeNull();
  expect(screen.getByText('<img src=x onerror="alert(1)"> & „Cleaner”')).toBeTruthy();
  expect(screen.getByText('Pokazuje <b>reklamy</b>.')).toBeTruthy();
  expect(screen.getByText('Reklamy')).toBeTruthy();
  expect(screen.getByText('Pochodzenie')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Usuń' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(screen.getByRole('button', { name: 'Wyłącz' }));
  expect(onlevel).toHaveBeenCalledWith('disable');
  await fireEvent.click(screen.getByRole('checkbox', { name: evil.name }));
  expect(ontoggle).toHaveBeenCalledOnce();
  expect(container.textContent).not.toMatch(/DM-/);
});
