import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { t } from '../lib/i18n/index.svelte';
import type { Notice } from '../lib/logic';
import NoticeLine from './NoticeLine.svelte';

const warn: Notice = { key: 'low_data', tone: 'warn', params: { hours: '1.5' } };
const info: Notice = { key: 'notifications_manual', tone: 'info', params: {} };

test('nothing to say: no line at all', () => {
  const { container } = render(NoticeLine, { props: { items: [] } });
  expect(container.textContent).toBe('');
});

test('one line with the first short note and +N; More shows every full text and details', async () => {
  render(NoticeLine, { props: { items: [warn, info], details: { low_data: ['adb: timeout'] } } });
  const line = screen.getByRole('status', { name: 'Uwagi do skanu' });
  expect(line.textContent).toContain(t('notice.short.low_data', { hours: '1.5' }));
  expect(line.textContent).toContain('+1');
  expect(screen.queryByText(t('summary.notifications_manual'))).toBeNull();
  const more = screen.getByRole('button', { name: 'Więcej' });
  expect(more.getAttribute('aria-expanded')).toBe('false');
  await fireEvent.click(more);
  expect(screen.getByText(t('summary.low_data', { hours: '1.5' }))).toBeTruthy();
  expect(screen.getByText(t('summary.notifications_manual'))).toBeTruthy();
  expect(screen.getByText('adb: timeout')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Zwiń' }));
  expect(screen.queryByText(t('summary.notifications_manual'))).toBeNull();
});

test('info only: neutral tone, no +N for a single note', () => {
  render(NoticeLine, { props: { items: [info] } });
  const line = screen.getByRole('status', { name: 'Uwagi do skanu' });
  expect(line.dataset.tone).toBe('info');
  expect(line.textContent).not.toContain('+');
});
