import { screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import type { AppView } from '../lib/types';
import { renderWith } from '../test-utils';
import AppRow from './AppRow.svelte';

const evil: AppView = {
  package: 'com.evil', name: '<img src=x onerror="alert(1)"> & „Cleaner”', score: 90,
  verdict: 'malicious', verdict_label: 'Szkodliwa', trusted: false, incomplete: false,
  is_system: false, from_play: false, installer: 'com.android.chrome', is_admin: true,
  default_level: 'remove', problems: ['Pokazuje <b>reklamy</b>.'], findings: [], apk_error: null,
  ad_sdks: null,
};

test('labels from the phone are shown literally, never as HTML', async () => {
  const { container } = await renderWith(AppRow, 'empty', { app: evil });
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('b b')).toBeNull();
  expect(screen.getByText('<img src=x onerror="alert(1)"> & „Cleaner”')).toBeTruthy();
  expect(screen.getByText('Pokazuje <b>reklamy</b>.')).toBeTruthy();
});
