import { render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import App from './App.svelte';

test('renders the brand', () => {
  render(App);
  expect(screen.getByText('DEMALWARE')).toBeTruthy();
});
