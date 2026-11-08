import { fireEvent, render, screen } from '@testing-library/svelte';
import Users from '@lucide/svelte/icons/users';
import { describe, expect, test, vi } from 'vitest';
import { snippet } from '../../test-utils';
import CategoryGroup from './CategoryGroup.svelte';
import CategoryRow from './CategoryRow.svelte';

const base = { icon: Users, name: 'Kontakty' };

describe('CategoryRow', () => {
  test('shows name, count, size and sub line', () => {
    render(CategoryRow, { ...base, count: '412', size: '1,2 GB', sub: 'na telefonie są już 3 kontakty' });
    expect(screen.getByText('Kontakty')).toBeTruthy();
    expect(screen.getByText('412')).toBeTruthy();
    expect(screen.getByText('1,2 GB')).toBeTruthy();
    expect(screen.getByText('na telefonie są już 3 kontakty')).toBeTruthy();
  });

  test('the fold is hidden by default and opens on click with aria-expanded', async () => {
    render(CategoryRow, { ...base, fold: snippet('lista aplikacji'), foldLabel: 'Aplikacje' });
    const btn = screen.getByRole('button', { name: /Pokaż/ });
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('lista aplikacji')).toBeNull();
    await fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('lista aplikacji')).toBeTruthy();
    expect(document.getElementById(btn.getAttribute('aria-controls')!)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Zwiń/ })).toBe(btn);
    await fireEvent.click(btn);
    expect(screen.queryByText('lista aplikacji')).toBeNull();
  });

  test('controlled fold follows foldOpen and reports onfold', async () => {
    const onfold = vi.fn();
    render(CategoryRow, { ...base, fold: snippet('szczegóły'), foldOpen: true, onfold });
    expect(screen.getByText('szczegóły')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /Zwiń/ }));
    expect(onfold).toHaveBeenCalledWith(false);
    expect(screen.getByText('szczegóły')).toBeTruthy(); // stan trzyma rodzic
  });

  test('result renders ✓ 412 in the ok tone and the warn tone separately', () => {
    const { unmount } = render(CategoryRow, { ...base, result: { text: '✓ 412', tone: 'ok' } });
    expect(screen.getByText('✓ 412').className).toContain('text-ok');
    unmount();
    render(CategoryRow, { ...base, result: { text: '44 z 46', tone: 'warn' } });
    expect(screen.getByText('44 z 46').className).toContain('text-warn');
  });

  test('the checkbox reports ontoggle and honours checked and disabled', async () => {
    const ontoggle = vi.fn();
    const { unmount } = render(CategoryRow, { ...base, checked: true, ontoggle });
    const box = screen.getByRole('checkbox', { name: 'Kontakty' }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    await fireEvent.click(box);
    expect(ontoggle).toHaveBeenCalledTimes(1);
    unmount();
    render(CategoryRow, { ...base, checked: false, disabled: true, ontoggle });
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true);
  });

  test('no checkbox without ontoggle and checked (result rows)', () => {
    render(CategoryRow, { ...base, result: { text: '✓ 1', tone: 'ok' } });
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  test('tone block tints the row, pills render', () => {
    const { container } = render(CategoryRow, { ...base, tone: 'block', pills: snippet('Xiaomi blokuje') });
    expect(container.querySelector('[data-tone="block"]')).toBeTruthy();
    expect(screen.getByText('Xiaomi blokuje')).toBeTruthy();
  });
});

describe('CategoryGroup', () => {
  test('renders title, rows and the grey empty line', () => {
    render(CategoryGroup, { title: 'Pliki', children: snippet('wiersz'), empty: 'muzyka' });
    expect(screen.getByText('Pliki')).toBeTruthy();
    expect(screen.getByText('wiersz')).toBeTruthy();
    expect(screen.getByText('Brak w kopii: muzyka')).toBeTruthy();
  });

  test('no empty line when empty is not given', () => {
    render(CategoryGroup, { title: 'Pliki', children: snippet('wiersz') });
    expect(screen.queryByText(/Brak w kopii/)).toBeNull();
  });
});
