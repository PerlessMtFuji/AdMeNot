<script lang="ts">
  import { getContext, onMount, untrack, type Component } from 'svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { createSettingsSearch } from '../../components/settings/search.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import { enter } from '../../lib/motion';
  import Icon from '../../ui/Icon.svelte';
  import { CATEGORIES, type SettingsCategory } from './categories';
  import Explorer from './Explorer.svelte';
  import General from './General.svelte';
  import Privacy from './Privacy.svelte';
  import Program from './Program.svelte';
  import Repair from './Repair.svelte';
  import Service from './Service.svelte';
  import SettingsCategorySection from './SettingsCategorySection.svelte';
  import Transfer from './Transfer.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const search = createSettingsSearch();

  const VIEWS: Record<SettingsCategory, Component> = {
    general: General, repair: Repair, transfer: Transfer, explorer: Explorer,
    service: Service, privacy: Privacy, program: Program,
  };
  const SAVED_MS = 2000;

  const searching = $derived(search.query.trim() !== '');
  const current = $derived(CATEGORIES.find((c) => c.id === s.settingsCategory) ?? CATEGORIES[0]);
  const View = $derived(VIEWS[current.id]);

  // Sekcje wyników zgłaszają po przerysowaniu, czy mają widoczny wiersz.
  const hits = new SvelteMap<SettingsCategory, boolean>();
  const noResults = $derived(searching && CATEGORIES.every((c) => hits.get(c.id) === false));
  $effect(() => {
    if (!searching) untrack(() => hits.clear());
  });

  // Zmiana kategorii albo `openSettings(kategoria)` (także tej samej) kończy wyszukiwanie.
  $effect(() => {
    void s.settingsCategory;
    void s.settingsOpened;
    untrack(() => { search.query = ''; });
  });

  function select(id: SettingsCategory): void {
    search.query = '';
    s.settingsCategory = id;
  }

  function onkeydown(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    search.query = '';
  }

  // „✓ Zapisano” tylko po zapisie zrobionym na tym ekranie; znika po 2 s, kolejny zapis odlicza od nowa.
  const openedWith = untrack(() => s.settingsSaved);
  let saved = $state(false);
  $effect(() => {
    const at = s.settingsSaved;
    if (at === 0 || at === openedWith) return;
    saved = true;
    const timer = setTimeout(() => { saved = false; }, SAVED_MS);
    return () => clearTimeout(timer);
  });

  onMount(() => { void ctl.loadService(); }); // kropka przy „Serwis i protokoły”
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <aside class="flex w-[260px] flex-none flex-col gap-1 border-r border-line px-3.5 py-5 max-[1200px]:w-[220px] max-[1200px]:px-2.5">
    <h1 class="mx-2.5 mb-3 text-2xl font-extrabold tracking-[-.01em]">{t('settings.title')}</h1>
    <div class="relative mb-3">
      <span class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-soft"><Icon name="search" size={16} /></span>
      <input type="search" class="field w-full rounded-xl py-2 pr-3 pl-9 text-sm" bind:value={search.query} {onkeydown}
        placeholder={t('settings.search')} aria-label={t('settings.search')} />
    </div>
    <nav aria-label={t('settings.categories')} class="flex flex-col gap-1">
      {#each CATEGORIES as c (c.id)}
        {@const on = c.id === current.id}
        <button type="button" data-category={c.id} aria-current={on ? 'page' : undefined} onclick={() => select(c.id)}
          class="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm font-semibold transition duration-150
            {on ? 'rail-now text-accent' : 'text-mut hover:bg-neutral-soft hover:text-ink'}">
          <span class="grid h-7 w-7 flex-none place-items-center rounded-lg transition-colors duration-150
            {on ? 'bg-accent text-white' : 'bg-neutral-soft'}">
            <Icon name={c.icon} size={16} />
          </span>
          <span class="min-w-0 flex-1">{t(c.labelKey)}</span>
          {#if c.id === 'service' && s.serviceNameMissing}
            <span data-dot aria-hidden="true" title={t('settings.service_missing')} class="h-[7px] w-[7px] flex-none rounded-full bg-warn-strong"></span>
          {/if}
        </button>
      {/each}
    </nav>
  </aside>

  <div class="relative flex min-w-0 flex-1">
    {#if saved}
      <div role="status" in:enter={{ y: -4 }}
        class="absolute top-3.5 right-[18px] z-10 flex items-center gap-1 rounded-full bg-ok-soft px-[11px] py-[5px] text-xs font-bold text-ok">
        <Icon name="check" size={13} strokeWidth={3} />{t('common.saved')}
      </div>
    {/if}
    <main class="min-w-0 flex-1 scroll-fade overflow-auto px-[26px] pt-5 pb-[30px]">
      <div class="mx-auto flex max-w-[760px] flex-col gap-3.5">
        {#if searching}
          {#each CATEGORIES as c (c.id)}
            {@const Rows = VIEWS[c.id]}
            <SettingsCategorySection category={c} onhits={(id, has) => hits.set(id, has)}><Rows /></SettingsCategorySection>
          {/each}
          {#if noResults}<p class="text-sm text-mut">{t('settings.no_results')}</p>{/if}
        {:else}
          <div class="flex flex-col gap-0.5 pr-24">
            <h2 class="text-lg font-extrabold">{t(current.labelKey)}</h2>
            <p class="text-xs text-mut">{t(current.leadKey)}</p>
          </div>
          <View />
        {/if}
      </div>
    </main>
  </div>
</div>
