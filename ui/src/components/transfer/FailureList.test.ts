import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, test } from 'vitest';
import type { FailureView } from '../../lib/types';
import FailureList from './FailureList.svelte';

const file = (i: number, over: Partial<FailureView> = {}): FailureView => ({ kind: 'file', group: 'photos', name: `IMG_${i}.jpg`,
  folder: 'DCIM/Camera', reason: 'denied', count: 1, retryable: true, ...over });

describe('FailureList', () => {
  test('shows the first 10 items and "Pokaż wszystkie (25)" reveals the rest', async () => {
    const failures = Array.from({ length: 25 }, (_, i) => file(i));
    render(FailureList, { props: { failures, limit: 10 } });
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
    await fireEvent.click(screen.getByRole('button', { name: 'Pokaż wszystkie (25)' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(25);
    expect(screen.queryByRole('button', { name: /Pokaż wszystkie/ })).toBeNull();
  });

  test('a file shows its name, folder and plain reason; no button when everything fits', () => {
    render(FailureList, { props: { failures: [file(1, { reason: 'no_space' })], limit: 10 } });
    expect(screen.getByText('IMG_1.jpg')).toBeTruthy();
    expect(screen.getByText('DCIM/Camera')).toBeTruthy();
    expect(screen.getByText(/brak miejsca/)).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  test('an item that cannot be retried says so', () => {
    render(FailureList, { props: { failures: [file(1, { reason: 'vanished', retryable: false }), file(2)], limit: 10 } });
    const items = screen.getAllByRole('listitem');
    expect(items[0].textContent).toContain('nie da się ponowić');
    expect(items[1].textContent).not.toContain('nie da się ponowić');
  });

  test('telephony shows the record count with the right plural', () => {
    const tel = (count: number): FailureView => ({ kind: 'tel', group: 'sms', name: 'sms', folder: '', reason: 'other', count, retryable: true });
    render(FailureList, { props: { failures: [tel(3)], limit: 10 } });
    expect(screen.getByText(/3 rekordy/)).toBeTruthy();
  });
});
