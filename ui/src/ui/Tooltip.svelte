<script lang="ts">
  import { onDestroy, type Snippet } from 'svelte';

  type Props = { text: string; side?: 'top' | 'bottom'; delay?: number; class?: string; children: Snippet };
  let { text, side = 'bottom', delay = 300, class: cls = '', children }: Props = $props();
  let visible = $state(false);
  let pos = $state({ x: 0, y: 0 });
  let host: HTMLElement;
  let timer: ReturnType<typeof setTimeout> | undefined;

  // Dymek ma position: fixed, więc nie ucina go overflow-hidden karty ani tabeli.
  function show() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const r = host.getBoundingClientRect();
      pos = { x: r.left + r.width / 2, y: side === 'bottom' ? r.bottom + 8 : r.top - 8 };
      visible = true;
    }, delay);
  }

  function hide() {
    clearTimeout(timer);
    visible = false;
  }

  // Przewijanie (także wewnętrznych kontenerów) zostawiłoby dymek w starym miejscu.
  $effect(() => {
    if (!visible) return;
    window.addEventListener('scroll', hide, true);
    return () => window.removeEventListener('scroll', hide, true);
  });

  onDestroy(() => clearTimeout(timer));
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span bind:this={host} data-tooltip-host class="relative inline-flex {cls}" onmouseenter={show} onmouseleave={hide}
  onpointerdown={hide} onclick={hide}
  onfocusin={show} onfocusout={hide} onkeydown={(e) => { if (e.key === 'Escape') hide(); }}>
  {@render children()}
  {#if visible}
    <span role="tooltip" style="left: {pos.x}px; top: {pos.y}px"
      class="pointer-events-none fixed z-50 max-w-[280px] -translate-x-1/2 rounded-lg bg-ink px-2.5 py-1.5 text-xs font-semibold text-surface shadow-[var(--shadow-raised)] {side === 'top' ? '-translate-y-full' : ''}">{text}</span>
  {/if}
</span>
