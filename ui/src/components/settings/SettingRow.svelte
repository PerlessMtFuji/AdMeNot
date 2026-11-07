<script lang="ts">
  import { getContext, type Snippet } from 'svelte';
  import { useSettingsSearch, GROUP_KEY, type GroupRegistry } from './search.svelte';

  type Props = { id: string; label: string; hint?: string; keywords?: string; dependent?: boolean;
    error?: string | null; stacked?: boolean; wide?: boolean; children: Snippet };
  let { id, label, hint, keywords, dependent = false, error = null, stacked = false, wide = false, children }: Props = $props();

  const search = useSettingsSearch();
  const group = getContext<GroupRegistry | undefined>(GROUP_KEY);
  const text = $derived(`${label} ${hint ?? ''} ${keywords ?? ''}`);
  const visible = $derived(search.matches(search.query, text));

  $effect(() => {
    if (!group) return;
    group.rows.set(id, visible ? '1' : '');
    return () => { group.rows.delete(id); };
  });
</script>

<div data-setting-id={id} hidden={!visible}
  class="border-t border-line py-[11px] pr-4 [h3+&]:border-t-0 {stacked ? 'flex flex-col items-stretch gap-1.5' : 'flex items-center gap-3.5'}
    {stacked && wide ? 'col-span-1 min-[900px]:col-span-2' : ''} {dependent ? 'bg-surface-2 pl-8' : 'pl-4'} {visible ? '' : 'hidden'}">
  <div class="min-w-0 flex-1">
    <b class="block text-sm font-bold">{label}</b>
    {#if hint}<span class="mt-px block text-xs text-mut">{hint}</span>{/if}
    {#if error}<span role="alert" class="mt-px block text-xs text-bad">{error}</span>{/if}
  </div>
  {@render children()}
</div>
