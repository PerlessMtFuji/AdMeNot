import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import App from './App.svelte';
import { setupCtl } from './test-utils';

test('shell: brand, five stages in the rail, history and settings toggle', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  expect(screen.getByText('AdMeNot')).toBeTruthy();
  const logo = screen.getByRole('navigation').querySelector('img');
  // Vite wstawia małe pliki jako data URI — wtedy rozpoznajemy ikonę po kolorze plakietki.
  const src = logo?.getAttribute('src') ?? '';
  expect(src.endsWith('admenot.svg') || decodeURIComponent(src).includes('#ef4444')).toBe(true);
  expect(logo?.getAttribute('alt')).toBe('');
  const stages = screen.getByRole('list', { name: 'Etapy' });
  expect(stages.children).toHaveLength(5);
  expect(stages.children[0].getAttribute('aria-current')).toBe('step');
  expect(stages.children[4].hasAttribute('title')).toBe(false);
  expect(stages.children[4].textContent).toContain('Protokół');
  await fireEvent.click(screen.getByRole('button', { name: 'Historia' }));
  await tick();
  expect(s.screen).toBe('history');
  expect(screen.queryByRole('list', { name: 'Etapy' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Nowe zlecenie' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Nowe zlecenie' }));
  expect(s.screen).toBe('main');
});
