import { render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import App from './App.svelte';
import { setupCtl } from './test-utils';

test('shell shows the header, stages and the connect screen', async () => {
  const { ctl } = await setupCtl('empty');
  render(App, { props: { ctl } });
  expect(screen.getByText('DEMALWARE')).toBeTruthy();
  expect(screen.getByText(/Czekam na telefon/)).toBeTruthy();
  expect(screen.getByRole('list', { name: 'Etapy' }).children).toHaveLength(5);
});
