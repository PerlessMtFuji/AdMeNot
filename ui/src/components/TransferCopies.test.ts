import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import type { CopyView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferCopies from './TransferCopies.svelte';

const COPY: CopyView = { id: 'OLD/1', serial: 'OLD', model: 'SM-A145R', manufacturer: 'samsung', client: 'Anna K.',
  created: '2026-10-25T14:30:00', expires: '2026-11-01T14:30:00', days_left: 7, status: 'complete', bytes: 10, counts: {},
  restores: [{ serial: 'NEW1', status: 'complete', updated: null, resumable: false },
    { serial: 'NEW2', status: 'stopped', updated: null, resumable: true }] };

async function show(copies: CopyView[], serial: string | null) {
  const env = await setupCtl('clean');
  env.s.transfer.copies = copies;
  env.s.devices = serial ? [{ serial, state: 'device', model: 'M', name: null, imei: null }] : [];
  env.s.serial = serial;
  render(TransferCopies, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return env;
}

describe('TransferCopies', () => {
  test('a finished copy can be uploaded to the connected phone and lists where it went', async () => {
    const env = await show([COPY], 'NEW3');
    expect(screen.getByText('wgrano na: NEW1')).toBeTruthy();
    expect(screen.getByText('wgrywanie przerwane: NEW2')).toBeTruthy();
    const plan = vi.spyOn(env.ctl, 'planRestore').mockResolvedValue();
    await fireEvent.click(screen.getByRole('button', { name: 'Wgraj na podłączony telefon' }));
    expect(plan).toHaveBeenCalledWith('OLD/1');
  });

  test('without a connected phone the upload button is off; an unfinished copy has none', async () => {
    await show([COPY, { ...COPY, id: 'OLD/2', status: 'in_progress', restores: [] }], null);
    const buttons = screen.getAllByRole('button', { name: 'Wgraj na podłączony telefon' }) as HTMLButtonElement[];
    expect(buttons).toHaveLength(1);
    expect(buttons[0].disabled).toBe(true);
  });
});
