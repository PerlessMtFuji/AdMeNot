import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import MirrorControls from './MirrorControls.svelte';

const flush = () => new Promise((r) => setTimeout(r, 0));
const PROPS = { serial: 'R58T00TEST', name: 'Galaxy A14' };

test('start, running, stop', async () => {
  const { s } = await renderWith(MirrorControls, 'empty', PROPS);
  await fireEvent.click(screen.getByRole('button', { name: 'Podgląd ekranu' }));
  await flush();
  await tick();
  expect(s.mirror.state).toBe('running');
  await fireEvent.click(screen.getByRole('button', { name: 'Zamknij podgląd' }));
  await flush();
  await tick();
  expect(screen.getByRole('button', { name: 'Podgląd ekranu' })).toBeTruthy();
});

test('another phone mirrored: this card still offers to start', async () => {
  const { s } = await renderWith(MirrorControls, 'empty', PROPS);
  s.mirror = { available: true, serial: 'OTHER', state: 'running', reason: null, blocked: false };
  await tick();
  expect(screen.getByRole('button', { name: 'Podgląd ekranu' })).toBeTruthy();
});

test('missing scrcpy disables the view but not the screenshot', async () => {
  const { s } = await renderWith(MirrorControls, 'empty', PROPS);
  s.mirror = { ...s.mirror, available: false };
  await tick();
  expect((screen.getByRole('button', { name: 'Podgląd ekranu' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/brak dołączonego scrcpy/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Zrzut ekranu' }));
  await flush();
  await tick();
  expect(screen.getByText('1 zrzut do protokołu')).toBeTruthy();
});

test('blocked control shows the Xiaomi hint while mirroring', async () => {
  const { s } = await renderWith(MirrorControls, 'empty', PROPS);
  s.mirror = { available: true, serial: PROPS.serial, state: 'running', reason: null, blocked: true };
  await tick();
  expect(screen.getByText(/Debugowanie USB \(ustawienia zabezpieczeń\)/)).toBeTruthy();
});
