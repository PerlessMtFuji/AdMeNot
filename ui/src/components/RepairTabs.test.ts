import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import type { PhoneBadge } from '../lib/logic';
import RepairTabs from './RepairTabs.svelte';

function mount(over: Partial<{ value: 'apps' | 'phone'; appsCount: number | null; phone: PhoneBadge }> = {}) {
  const onchange = vi.fn();
  render(RepairTabs, { props: { value: 'apps', appsCount: null, phone: { kind: 'ok' } as PhoneBadge, onchange, ...over } });
  return onchange;
}

test('tablist with two tabs wired to the panels', () => {
  mount({ value: 'phone' });
  expect(screen.getByRole('tablist').getAttribute('aria-label')).toBe('Widok kroku Naprawa');
  const apps = screen.getByRole('tab', { name: /Aplikacje/ });
  const phone = screen.getByRole('tab', { name: /Telefon/ });
  expect(apps.getAttribute('aria-selected')).toBe('false');
  expect(phone.getAttribute('aria-selected')).toBe('true');
  expect(apps.getAttribute('aria-controls')).toBe('repair-panel-apps');
  expect(phone.getAttribute('aria-controls')).toBe('repair-panel-phone');
  expect(apps.id).toBe('repair-tab-apps');
  expect(phone.id).toBe('repair-tab-phone');
  expect(apps.getAttribute('tabindex')).toBe('-1');
  expect(phone.getAttribute('tabindex')).toBe('0');
});

test('apps badge shows the count, and is absent for null', () => {
  mount({ appsCount: 3 });
  expect(screen.getByRole('tab', { name: /Aplikacje/ }).textContent).toContain('3');
});

test('no apps badge when the count is null', () => {
  mount({ appsCount: null });
  expect(screen.getByRole('tab', { name: 'Aplikacje' })).toBeTruthy();
});

test('phone badge: count, ok check and unknown question mark with accessible names', () => {
  const a = render(RepairTabs, { props: { value: 'apps', appsCount: null, phone: { kind: 'count', count: 2 } as PhoneBadge, onchange: vi.fn() } });
  expect(screen.getByRole('tab', { name: /Telefon/ }).textContent).toContain('2');
  a.unmount();
  const b = render(RepairTabs, { props: { value: 'apps', appsCount: null, phone: { kind: 'ok' } as PhoneBadge, onchange: vi.fn() } });
  expect(screen.getByRole('img', { name: 'Wszystko w porządku' })).toBeTruthy();
  b.unmount();
  render(RepairTabs, { props: { value: 'apps', appsCount: null, phone: { kind: 'unknown' } as PhoneBadge, onchange: vi.fn() } });
  const q = screen.getByRole('img', { name: 'Nie wszystko udało się odczytać' });
  expect(q.textContent).toContain('?');
});

test('click and left/right arrows switch to the other tab', async () => {
  const onchange = mount({ value: 'apps' });
  await fireEvent.click(screen.getByRole('tab', { name: /Telefon/ }));
  expect(onchange).toHaveBeenLastCalledWith('phone');
  await fireEvent.keyDown(screen.getByRole('tab', { name: /Aplikacje/ }), { key: 'ArrowRight' });
  expect(onchange).toHaveBeenLastCalledWith('phone');
  await fireEvent.keyDown(screen.getByRole('tab', { name: /Aplikacje/ }), { key: 'ArrowLeft' });
  expect(onchange).toHaveBeenLastCalledWith('phone');
  await fireEvent.keyDown(screen.getByRole('tab', { name: /Telefon/ }), { key: 'ArrowLeft' });
  expect(onchange).toHaveBeenLastCalledWith('apps');
});

test('arrow keydowns never bubble to the expert table handler', () => {
  mount();
  const seen = vi.fn();
  document.body.addEventListener('keydown', seen);
  const tab = screen.getByRole('tab', { name: /Aplikacje/ });
  for (const key of ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft']) {
    tab.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
  }
  document.body.removeEventListener('keydown', seen);
  expect(seen).not.toHaveBeenCalled();
});

test('ArrowRight moves focus to the other tab', async () => {
  // Rodzic zmienia value po onchange — tu wystarczy fokus ustawiony przez komponent.
  mount({ value: 'apps' });
  const apps = screen.getByRole('tab', { name: /Aplikacje/ });
  apps.focus();
  await fireEvent.keyDown(apps, { key: 'ArrowRight' });
  expect(document.activeElement).toBe(screen.getByRole('tab', { name: /Telefon/ }));
});

test('arrows with Alt, Ctrl or Meta are left to the browser', async () => {
  const onchange = mount({ value: 'apps' });
  const apps = screen.getByRole('tab', { name: /Aplikacje/ });
  for (const mod of ['altKey', 'ctrlKey', 'metaKey']) {
    const ev = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true, [mod]: true });
    apps.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  }
  expect(onchange).not.toHaveBeenCalled();
});

test('modified arrows still bubble (component does not stop them)', () => {
  mount();
  const seen = vi.fn();
  document.body.addEventListener('keydown', seen);
  screen.getByRole('tab', { name: /Aplikacje/ }).dispatchEvent(
    new KeyboardEvent('keydown', { key: 'ArrowLeft', altKey: true, bubbles: true, cancelable: true }));
  document.body.removeEventListener('keydown', seen);
  expect(seen).toHaveBeenCalledTimes(1);
});
