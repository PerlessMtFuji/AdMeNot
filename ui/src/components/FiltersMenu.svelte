<script lang="ts">
  import { getContext } from 'svelte';
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { SOURCE_NON_PLAY } from '../lib/logic';
  import type { Category } from '../lib/types';
  import Icon from '../ui/Icon.svelte';

  type Facets = { categories: { value: Category; count: number }[]; sources: { value: string; count: number }[]; nonPlay: number };
  let { facets }: { facets: Facets } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let open = $state(false);
  let root: HTMLElement;
  const active = $derived(s.categoryFilter.length + (s.sourceFilter ? 1 : 0));
  // Wybrana opcja zostaje na liście z zerem, gdy wyszukiwarka ją ukryje.
  const typeChips = $derived([...facets.categories, ...s.categoryFilter
    .filter((c) => !facets.categories.some((f) => f.value === c)).map((value) => ({ value, count: 0 }))]);
  const sourceOptions = $derived(s.sourceFilter && s.sourceFilter !== SOURCE_NON_PLAY && !facets.sources.some((f) => f.value === s.sourceFilter)
    ? [...facets.sources, { value: s.sourceFilter, count: 0 }] : facets.sources);

  function toggleType(c: Category) {
    s.categoryFilter = s.categoryFilter.includes(c) ? s.categoryFilter.filter((x) => x !== c) : [...s.categoryFilter, c];
  }
  function clear() {
    s.categoryFilter = [];
    s.sourceFilter = null;
  }
</script>

<!-- Klik poza menu: composedPath zamiast contains, bo klik w „Wyczyść filtry” usuwa własny cel z DOM. -->
<svelte:window onkeydown={(e) => { if (open && e.key === 'Escape') open = false; }}
  onclick={(e) => { if (open && !e.composedPath().includes(root)) open = false; }} />

<div class="relative" bind:this={root}>
  <button type="button" aria-expanded={open} onclick={() => (open = !open)}
    class="field flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-semibold {active ? 'text-accent' : 'text-mut'}">
    {active ? t('expert.filters_active', { count: active }) : t('expert.filters')}<Icon name="chevron-down" size={14} />
  </button>
  {#if open}
    <div role="group" aria-label={t('expert.filters')}
      class="absolute top-full right-0 z-20 mt-2 flex w-[340px] flex-col gap-3 rounded-2xl card p-4 shadow-xl">
      <div role="group" aria-label={t('expert.filter_types')} class="flex flex-wrap gap-1.5">
        {#each typeChips as c (c.value)}
          {@const on = s.categoryFilter.includes(c.value)}
          <button type="button" aria-pressed={on} onclick={() => toggleType(c.value)}
            class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ring-1 ring-inset transition duration-150
              {on ? 'bg-accent-soft text-accent ring-current/30' : 'text-mut ring-line hover:text-ink'}">
            <Icon name={CATEGORY_ICON[c.value]} size={14} />{t(categoryKey(c.value))}<span class="mono text-2xs opacity-70">{c.count}</span>
          </button>
        {/each}
      </div>
      <select aria-label={t('expert.filter_source')} value={s.sourceFilter ?? ''}
        onchange={(e) => (s.sourceFilter = e.currentTarget.value || null)}
        class="field rounded-[10px] px-2.5 py-1.5 text-sm font-semibold {s.sourceFilter ? 'text-accent' : 'text-mut'}">
        <option value="">{t('expert.all_sources')}</option>
        {#if facets.nonPlay > 0 || s.sourceFilter === SOURCE_NON_PLAY}
          <option value={SOURCE_NON_PLAY}>{t('expert.source_non_play')} · {facets.nonPlay}</option>
        {/if}
        {#each sourceOptions as o (o.value)}<option value={o.value}>{o.value} · {o.count}</option>{/each}
      </select>
      {#if active}<button type="button" class="self-start text-sm font-semibold text-accent hover:underline" onclick={clear}>{t('expert.clear_filters')}</button>{/if}
    </div>
  {/if}
</div>
