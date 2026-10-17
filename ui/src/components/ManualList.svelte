<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { formatEta } from '../lib/eta';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { facetCounts, manualRows } from '../lib/logic';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import ApkProgress from './ApkProgress.svelte';
  import FiltersMenu from './FiltersMenu.svelte';
  import ManualRow from './ManualRow.svelte';

  // Tryb ręczny (spec §3.2): bez grup werdyktu i zaznaczania zbiorczego.
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const apps = $derived(s.scan?.apps ?? []);
  const rows = $derived(manualRows(apps, { query: s.query, showSystem: s.showSystem, source: s.sourceFilter }));
  // Tylko filtr źródła: rodzaje to objawy z ukrytych heurystyk.
  const facets = $derived({ ...facetCounts(manualRows(apps, { query: s.query, showSystem: s.showSystem, source: null })),
    categories: [] });
  const picked = $derived(Object.keys(s.selection).length);
  const allEta = $derived(formatEta(s.apkEstimate, i18n.lang));
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-3">
    <label class="field flex flex-1 items-center gap-2.5 rounded-xl px-3.5 py-2 text-soft">
      <Icon name="search" />
      <!-- svelte-ignore a11y_autofocus -->
      <input type="search" autofocus class="flex-1 bg-transparent text-ink outline-none" bind:value={s.query}
        placeholder={t('manual.search')} aria-label={t('manual.search')} />
    </label>
    <FiltersMenu {facets} />
    <label class="flex items-center gap-2 text-sm whitespace-nowrap text-mut">
      <input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" bind:checked={s.showSystem} />{t('manual.show_system')}
    </label>
  </div>
  {#if s.apk.running}
    <ApkProgress />
  {:else}
    <div class="flex flex-wrap gap-2">
      <Button variant="primary" disabled={!picked || s.orderRunning} onclick={() => ctl.analyzeSelected()}>
        {t('manual.analyze_selected', { count: picked, eta: picked ? formatEta(s.selectionEta, i18n.lang) : '' }).trim()}
      </Button>
      <Button disabled={s.orderRunning} onclick={() => ctl.analyzeAll()}>{t('manual.analyze_all', { eta: allEta })}</Button>
    </div>
  {/if}
  {#each rows as app (app.package)}<ManualRow {app} />{:else}<p class="py-6 text-center text-mut">{t('manual.empty')}</p>{/each}
  {#if rows.length > 8 && !s.apk.running}
    <Button class="self-center" disabled={s.orderRunning} onclick={() => ctl.analyzeAll()}>{t('manual.analyze_all', { eta: allEta })}</Button>
  {/if}
</div>
