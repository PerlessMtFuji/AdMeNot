<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import { enter } from '../../lib/motion';

  /** Stan pusty z ilustracją: pusty folder, brak wyników filtra, telefon odłączony (kłódka — folder bez dostępu). */
  type Kind = 'folder' | 'filter' | 'offline' | 'locked';
  let { kind }: { kind: Kind } = $props();

  const TEXT: Record<Kind, [string, string]> = {
    folder: ['explorer.empty.folder', 'explorer.empty.folder_text'],
    filter: ['explorer.empty.filter', 'explorer.empty.filter_text'],
    offline: ['explorer.offline.title', 'explorer.offline.text'],
    locked: ['explorer.locked.title', 'explorer.locked.text'],
  };
  const [title, text] = $derived(TEXT[kind]);
</script>

<div in:enter data-empty={kind} class="m-auto flex max-w-[380px] flex-col items-center gap-2 p-6 text-center">
  <svg viewBox="0 0 96 80" width="120" height="100" fill="none" aria-hidden="true" class="text-soft">
    <ellipse cx="48" cy="72" rx="30" ry="4" fill="currentColor" opacity=".15" />
    {#if kind === 'folder'}
      <path d="M12 24a6 6 0 0 1 6-6h16l8 8h36a6 6 0 0 1 6 6v30a6 6 0 0 1-6 6H18a6 6 0 0 1-6-6Z" fill="var(--color-warn-soft)"
        stroke="var(--color-warn-strong)" stroke-width="2.5" stroke-linejoin="round" />
      <path d="M36 50h24" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="1 6" />
    {:else if kind === 'filter'}
      <circle cx="42" cy="36" r="18" fill="var(--color-accent-soft)" stroke="var(--color-accent)" stroke-width="2.5" />
      <path d="m55 49 14 14" stroke="var(--color-accent)" stroke-width="4" stroke-linecap="round" />
      <path d="M35 30l14 12M49 30 35 42" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
    {:else if kind === 'offline'}
      <rect x="30" y="8" width="36" height="58" rx="7" fill="var(--color-surface-2)" stroke="currentColor" stroke-width="2.5" />
      <path d="M44 56h8" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
      <path d="M48 66v6M40 72h16" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
      <path d="M38 24l20 20M58 24 38 44" stroke="var(--color-warn-strong)" stroke-width="3" stroke-linecap="round" />
    {:else}
      <path d="M12 24a6 6 0 0 1 6-6h16l8 8h36a6 6 0 0 1 6 6v30a6 6 0 0 1-6 6H18a6 6 0 0 1-6-6Z" fill="var(--color-surface-2)"
        stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" />
      <rect x="38" y="40" width="20" height="16" rx="3" fill="currentColor" />
      <path d="M42 40v-4a6 6 0 0 1 12 0v4" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
    {/if}
  </svg>
  <b class="text-ink">{t(title)}</b>
  <p class="text-sm text-mut">{t(text)}</p>
</div>
