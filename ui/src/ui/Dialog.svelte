<script lang="ts">
  import type { Snippet } from 'svelte';
  import { fade, scale } from 'svelte/transition';
  import { DUR, ms } from '../lib/motion';

  type Props = { title: string; children: Snippet; actions: Snippet; oncancel: () => void };
  let { title, children, actions, oncancel }: Props = $props();
  let box: HTMLDivElement;
  const id = `dialog-${Math.random().toString(36).slice(2, 9)}`;
  const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

  $effect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => previous?.focus?.();
  });

  function keydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      oncancel();
      return;
    }
    if (e.key !== 'Tab') return;
    const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<div class="fixed inset-0 z-50 grid place-items-center bg-[rgb(15_23_42/.45)] backdrop-blur-[6px]"
  transition:fade={{ duration: ms(DUR.micro) }}>
  <div bind:this={box} role="dialog" aria-modal="true" aria-labelledby={id} tabindex="-1" onkeydown={keydown}
    class="w-[min(500px,92vw)] rounded-[20px] card p-6"
    transition:scale={{ start: 0.96, duration: ms(DUR.dialog) }}>
    <h2 {id} class="text-lg font-bold">{title}</h2>
    <div class="mt-2 text-mut">{@render children()}</div>
    <div class="mt-6 flex justify-end gap-2">{@render actions()}</div>
  </div>
</div>
