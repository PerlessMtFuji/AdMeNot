<script lang="ts">
  import type { Snippet } from 'svelte';
  import { enter } from '../lib/motion';
  import Icon, { type IconName } from './Icon.svelte';

  type Props = { tone: 'warn' | 'info' | 'bad' | 'ok'; icon: IconName; title?: string; children?: Snippet;
    actions?: Snippet };
  let { tone, icon, title, children, actions }: Props = $props();
  const BOX = {
    warn: 'border-warn-strong/40 bg-warn-soft', info: 'border-line bg-surface',
    bad: 'border-bad/30 bg-bad-soft', ok: 'border-ok/30 bg-ok-soft',
  };
  const DOT = {
    warn: 'bg-warn-strong/25 text-warn', info: 'bg-accent-soft text-accent',
    bad: 'bg-bad/15 text-bad', ok: 'bg-ok/15 text-ok',
  };
  const TEXT = { warn: 'text-warn', info: 'text-mut', bad: 'text-bad', ok: 'text-ok' };
</script>

<div role={tone === 'bad' ? 'alert' : 'status'} in:enter
  class="flex items-center gap-3 rounded-2xl border px-4 py-3 {BOX[tone]}">
  <span class="grid h-8 w-8 flex-none place-items-center rounded-full {DOT[tone]}"><Icon name={icon} size={16} /></span>
  <div class="min-w-0 flex-1">
    {#if title}<b class="block text-ink">{title}</b>{/if}
    {#if children}<div class={TEXT[tone]}>{@render children()}</div>{/if}
  </div>
  {#if actions}<div class="flex flex-none items-center gap-2">{@render actions()}</div>{/if}
</div>
