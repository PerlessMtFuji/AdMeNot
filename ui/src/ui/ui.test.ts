import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import { snippet } from '../test-utils';
import Button from './Button.svelte';
import CountUp from './CountUp.svelte';
import Dialog from './Dialog.svelte';
import Icon, { ICONS } from './Icon.svelte';
import Progress from './Progress.svelte';
import Segmented from './Segmented.svelte';
import Tooltip from './Tooltip.svelte';

describe('base components', () => {
  test('Segmented marks the chosen option and reports a change', async () => {
    const onchange = vi.fn();
    render(Segmented, { props: { label: 'Akcja', value: 'remove', onchange, options: [
      { value: 'silence', label: 'Wycisz' }, { value: 'disable', label: 'Wyłącz' },
      { value: 'remove', label: 'Usuń', tone: 'bad' }] } });
    expect(screen.getByRole('group', { name: 'Akcja' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Usuń' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Wycisz' }).getAttribute('aria-pressed')).toBe('false');
    await fireEvent.click(screen.getByRole('button', { name: 'Wyłącz' }));
    expect(onchange).toHaveBeenCalledWith('disable');
  });

  test('Button: pressed state and disabled', () => {
    render(Button, { props: { pressed: true, disabled: true, children: snippet('Ekspert') } });
    const button = screen.getByRole('button', { name: 'Ekspert' }) as HTMLButtonElement;
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(button.disabled).toBe(true);
  });

  test('Dialog: focus on the first button, Tab wraps, Escape cancels', async () => {
    const oncancel = vi.fn();
    render(Dialog, { props: { title: 'Trwa zlecenie', oncancel, children: snippet('Przerwać?'),
      actions: createActions() } });
    await tick();
    const dialog = screen.getByRole('dialog', { name: 'Trwa zlecenie' });
    const [first, last] = screen.getAllByRole('button');
    expect(document.activeElement).toBe(first);
    last.focus();
    await fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
    await fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(oncancel).toHaveBeenCalledOnce();
  });

  test('CountUp lands on the value (reduced motion in tests)', async () => {
    const { container, rerender } = render(CountUp, { props: { value: 7 } });
    await tick();
    expect(container.textContent).toBe('7');
    await rerender({ value: 12 });
    await tick();
    expect(container.textContent).toBe('12');
  });

  test('Progress exposes its value', () => {
    render(Progress, { props: { value: 0.42, label: 'Postęp' } });
    expect(screen.getByRole('progressbar', { name: 'Postęp' }).getAttribute('aria-valuenow')).toBe('42');
  });

  test('every icon renders an svg', () => {
    for (const name of Object.keys(ICONS) as (keyof typeof ICONS)[]) {
      const { container, unmount } = render(Icon, { props: { name } });
      expect(container.querySelector('svg'), name).toBeTruthy();
      unmount();
    }
  });
});

function createActions() {
  return snippet('<button>Anuluj</button><button>Przerwij</button>');
}

describe('Tooltip', () => {
  const setup = () => {
    render(Tooltip, { props: { text: 'Podpowiedź', children: snippet('<button type="button">cel</button>') } });
    return screen.getByRole('button', { name: 'cel' });
  };

  test('shows after a delay on hover and hides on leave', async () => {
    vi.useFakeTimers();
    try {
      const trigger = setup();
      await fireEvent.mouseEnter(trigger.closest('[data-tooltip-host]')!);
      expect(screen.queryByRole('tooltip')).toBeNull();
      await vi.advanceTimersByTimeAsync(350);
      expect(screen.getByRole('tooltip').textContent).toBe('Podpowiedź');
      await fireEvent.mouseLeave(trigger.closest('[data-tooltip-host]')!);
      expect(screen.queryByRole('tooltip')).toBeNull();
    } finally { vi.useRealTimers(); }
  });

  test('a short hover does not show it', async () => {
    vi.useFakeTimers();
    try {
      const trigger = setup();
      await fireEvent.mouseEnter(trigger.closest('[data-tooltip-host]')!);
      await vi.advanceTimersByTimeAsync(100);
      await fireEvent.mouseLeave(trigger.closest('[data-tooltip-host]')!);
      await vi.advanceTimersByTimeAsync(500);
      expect(screen.queryByRole('tooltip')).toBeNull();
    } finally { vi.useRealTimers(); }
  });

  test('shows on keyboard focus, hides on Escape and on blur', async () => {
    vi.useFakeTimers();
    try {
      const trigger = setup();
      trigger.focus();
      await vi.advanceTimersByTimeAsync(350);
      expect(screen.getByRole('tooltip')).toBeTruthy();
      await fireEvent.keyDown(trigger, { key: 'Escape' });
      expect(screen.queryByRole('tooltip')).toBeNull();
      trigger.blur();
      trigger.focus();
      await vi.advanceTimersByTimeAsync(350);
      expect(screen.getByRole('tooltip')).toBeTruthy();
      trigger.blur();
      await tick();
      expect(screen.queryByRole('tooltip')).toBeNull();
    } finally { vi.useRealTimers(); }
  });

  test('hides on click and on scroll so no stale bubble stays', async () => {
    vi.useFakeTimers();
    try {
      const trigger = setup();
      const host = trigger.closest('[data-tooltip-host]')!;
      await fireEvent.mouseEnter(host);
      await vi.advanceTimersByTimeAsync(350);
      expect(screen.getByRole('tooltip')).toBeTruthy();
      await fireEvent.click(trigger);
      expect(screen.queryByRole('tooltip')).toBeNull();
      await fireEvent.mouseEnter(host);
      await vi.advanceTimersByTimeAsync(350);
      expect(screen.getByRole('tooltip')).toBeTruthy();
      await fireEvent.scroll(document.body);
      expect(screen.queryByRole('tooltip')).toBeNull();
    } finally { vi.useRealTimers(); }
  });
});
