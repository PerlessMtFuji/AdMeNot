import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { t } from '../lib/i18n/index.svelte';
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

test('a restore from backup says it takes a while', () => {
  const step = { action_id: 1, package: 'p', name: 'P', kind: 'installed', label: 'przywrócenie', status: 'running',
    error: null, restore_bytes: 50 * 1024 ** 2 } as never;
  const { container } = render(StepTimeline, { props: { steps: [step] } });
  expect(container.textContent).toContain(t('history.restoring', { size: '50 MB' }));
});
