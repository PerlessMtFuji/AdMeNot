<script lang="ts">
  import { setContext, type Snippet } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { GROUP_KEY, type GroupRegistry } from './search.svelte';

  type Props = { title: string; children: Snippet };
  let { title, children }: Props = $props();

  const registry: GroupRegistry = { rows: new SvelteMap<string, string>() };
  setContext(GROUP_KEY, registry);
  // Wiersze zawsze są zamontowane (zgłaszają widoczność); grupa chowa się, gdy żaden nie pasuje.
  const anyVisible = $derived([...registry.rows.values()].some((v) => v === '1') || registry.rows.size === 0);
</script>

<section data-setting-group hidden={!anyVisible} aria-label={title}
  class="card flex-none overflow-hidden rounded-[14px] {anyVisible ? '' : 'hidden'}">
  <h3 class="px-4 pt-[11px] pb-1 text-xs font-extrabold tracking-wide text-soft uppercase">{title}</h3>
  {@render children()}
</section>
