import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import SiteQueue from './SiteQueue.svelte';

const CHROME = 'com.android.chrome';
const site = (id: number) => ({ action_id: id, package: CHROME, browser: 'Chrome', site: `s${id}.example` });
const undone = (id: number) => ({ action_id: id, package: CHROME, name: 'Chrome', kind: 'channel', label: '',
  status: 'undone' as const, error: null, error_key: null });
const wait = (id: number) => ({ package: CHROME, name: 'Chrome', kind: 'channel' as const, browser: 'Chrome',
  site: `s${id}.example`, timeout: 180, action_id: id, since: Date.now() });

test('skip calls skip_site', async () => {
  const { s, bridge } = await renderWith(SiteQueue);
  s.undoSites = [site(1), site(2)];
  s.userWait = wait(1);
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Pomiń' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'skip_site', args: [] });
});

test('more than three restored sites collapse into one line', async () => {
  const { s } = await renderWith(SiteQueue);
  s.undoSites = [1, 2, 3, 4, 5].map(site);
  s.undoSteps = [1, 2, 3, 4].map(undone);
  s.userWait = wait(5);
  await tick();
  expect(screen.getByText('✓ 4 włączone')).toBeTruthy();
  expect(screen.queryByText('Chrome · s1.example')).toBeNull();
  expect(screen.getByText('Chrome · s5.example')).toBeTruthy();
  s.undoSteps = [1, 2, 3].map(undone); // trzy zrobione jeszcze widać pojedynczo
  s.userWait = wait(4);
  await tick();
  expect(screen.queryByText(/✓ \d+ włączon/)).toBeNull();
  expect(screen.getByText('Chrome · s1.example')).toBeTruthy();
});
