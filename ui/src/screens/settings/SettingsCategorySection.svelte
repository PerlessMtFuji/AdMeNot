<script lang="ts">
  import { tick, type Snippet } from 'svelte';
  import { useSettingsSearch } from '../../components/settings/search.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { CategoryInfo, SettingsCategory } from './categories';

  type Props = { category: CategoryInfo; onhits: (id: SettingsCategory, hits: boolean) => void; children: Snippet };
  let { category, onhits, children }: Props = $props();

  const search = useSettingsSearch();
  let el = $state<HTMLElement>();
  let hits = $state(true);

  // Wiersze zostają zamontowane i chowają się atrybutem `hidden`, więc liczymy tylko widoczne
  // w widocznych grupach — dopiero po przerysowaniu, gdy wiersze i grupy zdążą się ukryć.
  function visibleRows(root: HTMLElement): number {
    return [...root.querySelectorAll<HTMLElement>('[data-setting-id]:not([hidden])')]
      .filter((row) => !row.closest<HTMLElement>('[data-setting-group]')?.hidden).length;
  }

  $effect(() => {
    const q = search.query;
    const root = el;
    if (!root) return;
    let live = true;
    tick().then(() => {
      if (!live || q !== search.query) return;
      hits = visibleRows(root) > 0;
      onhits(category.id, hits);
    });
    return () => { live = false; };
  });
</script>

<section bind:this={el} data-settings-section={category.id} hidden={!hits} aria-label={t(category.labelKey)}
  class="flex flex-col gap-3.5 {hits ? '' : 'hidden'}">
  <h2 class="text-lg font-extrabold">{t(category.labelKey)}</h2>
  {@render children()}
</section>
