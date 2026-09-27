import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import StepTimeline from './StepTimeline.svelte';

test('each step shows its state and the error under a failed step', () => {
  const step = (action_id: number, status: string, error: string | null = null) => ({
    action_id, package: 'p', name: 'P', kind: 'enabled', label: `krok ${action_id}`, status, error }) as never;
  const { container } = render(StepTimeline, { props: { steps: [
    step(1, 'done'), step(2, 'running'), step(3, 'failed', 'Telefon odrzucił polecenie.'), step(4, 'skipped')] } });
  const items = [...container.querySelectorAll('li')];
  expect(items.map((li) => li.dataset.status)).toEqual(['done', 'running', 'failed', 'skipped']);
  expect(items[1].querySelector('.spin')).toBeTruthy();
  expect(items[2].textContent).toContain('Telefon odrzucił polecenie.');
});
