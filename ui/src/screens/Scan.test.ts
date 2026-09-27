import { screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import Scan from './Scan.svelte';

test('scan screen: stage checklist, then the phone photo with the scan line', async () => {
  const { s, container } = await renderWith(Scan, 'adware');
  s.phase = 'scanning';
  s.scanStage = 'packages';
  await tick();
  expect(screen.getByRole('heading', { name: 'Skanuję telefon' })).toBeTruthy();
  const items = screen.getByRole('list', { name: 'Etapy skanowania' }).querySelectorAll('li');
  expect([...items].map((li) => li.dataset.status)).toEqual(['done', 'on', 'todo', 'todo']);
  expect(screen.getAllByText('SM A145R').length).toBeGreaterThan(0);
  s.device = { serial: 'R58T00TEST', name: 'Galaxy A14', brand: 'samsung', manufacturer: 'samsung',
    model: 'SM-A145R', market_name: 'Galaxy A14', android: '14', sdk: 34, patch: null, uptime_s: 60,
    match: null, image: 'data:image/svg+xml;base64,PHN2Zy8+' };
  await tick();
  expect(screen.getAllByAltText('Galaxy A14').length).toBeGreaterThan(0);
  expect(container.querySelector('.scanline')).toBeTruthy();
});
