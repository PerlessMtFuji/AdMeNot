<script lang="ts">
  import type { Snippet } from 'svelte';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { DUR, ms } from '../../lib/motion';

  /** Przycisk z rozwijanym menu (Nowy ▾, Wgraj tutaj ▾, ⋯). `up` — menu nad przyciskiem (pasek na dole ekranu). */
  export interface MenuItem { id: string; label: string; sub?: string; onselect: () => void }
  type Props = { items: MenuItem[]; label?: string; title?: string; menuLabel: string; up?: boolean;
    disabled?: boolean; class?: string; children: Snippet };
  let { items, label, title, menuLabel, up = false, disabled = false, class: cls = '', children }: Props = $props();
  let open = $state(false);
  let root: HTMLElement;
  let list = $state<HTMLElement>();

  $effect(() => {
    if (open) list?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  });

  function pick(item: MenuItem): void {
    open = false;
    item.onselect();
  }

  /** Strzałki między pozycjami, Esc zamyka (fokus wraca na przycisk). */
  function onkey(e: KeyboardEvent): void {
    const all = Array.from(list?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    const i = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      all[(i + (e.key === 'ArrowDown' ? 1 : all.length - 1)) % all.length]?.focus();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      open = false;
      root.querySelector<HTMLElement>('button')?.focus();
    }
  }
</script>

<svelte:window onclick={(e) => { if (open && !e.composedPath().includes(root)) open = false; }} />

<div class="relative flex-none" bind:this={root}>
  <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={label} {title} {disabled}
    onclick={() => (open = !open)}
    class="inline-flex items-center justify-center gap-1.5 font-semibold whitespace-nowrap transition duration-150
      enabled:active:translate-y-px disabled:cursor-default disabled:opacity-50 {cls}">
    {@render children()}
  </button>
  {#if open}
    <div bind:this={list} role="menu" aria-label={menuLabel} tabindex="-1" onkeydown={onkey}
      transition:fly={{ y: up ? 6 : -6, duration: ms(DUR.micro), easing: cubicOut }}
      class="absolute right-0 z-30 flex min-w-[210px] flex-col gap-0.5 rounded-2xl card p-1.5 shadow-xl
        {up ? 'bottom-full mb-2' : 'top-full mt-2'}">
      {#each items as item (item.id)}
        <button type="button" role="menuitem" onclick={() => pick(item)}
          class="flex flex-col items-start rounded-xl px-3 py-2 text-left text-sm font-semibold text-ink outline-none
            transition-colors duration-150 hover:bg-neutral-soft focus-visible:bg-accent-soft">
          {item.label}
          {#if item.sub}<span class="text-2xs font-medium text-mut">{item.sub}</span>{/if}
        </button>
      {/each}
    </div>
  {/if}
</div>
