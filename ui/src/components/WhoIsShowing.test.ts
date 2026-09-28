import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import WhoIsShowing from './WhoIsShowing.svelte';

test('who is showing: asks the phone and lists the packages literally', async () => {
  const ask = vi.fn().mockResolvedValue({
    resumed: { package: 'com.evil', name: '<b>Evil</b>' },
    overlays: [{ package: 'com.evil', name: '<b>Evil</b>' }], errors: [],
  });
  render(WhoIsShowing, { props: { ask } });
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  expect(ask).toHaveBeenCalledOnce();
  expect((await screen.findAllByText('<b>Evil</b>', { exact: false })).length).toBeGreaterThan(0);
});
