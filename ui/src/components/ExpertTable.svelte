<script lang="ts">
  import { getContext, tick } from 'svelte';
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { initial, LEVEL_TONE, moveFocus } from '../lib/logic';
  import type { AppView, Category, Level } from '../lib/types';
  import CountUp from '../ui/CountUp.svelte';
  import Icon, { type IconName } from '../ui/Icon.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import AppIcon from './AppIcon.svelte';

  type Facets = { categories: { value: Category; count: number }[]; sources: { value: string; count: number }[] };
  let { rows, focused, facets }: { rows: AppView[]; focused: string | null; facets: Facets } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const counts = $derived(s.scan!.counts);
  const collectors = $derived(s.scan!.collectors);
  const apk = $derived(s.scan!.apk);
  const complete = $derived(collectors.ok === collectors.total && (!apk || Object.keys(apk.failed).length === 0));
  const filters = $derived([
    { value: 'attention', label: t('expert.filter_attention', { count: counts.total - counts.safe }) },
    { value: 'all', label: t('expert.filter_all', { count: counts.total }) },
  ]);
  const SCORE = { malicious: 'text-bad', suspicious: 'text-warn', review: 'text-neutral', safe: 'text-ok' };
  const BAR = { malicious: 'bg-bad', suspicious: 'bg-warn-strong', review: 'bg-soft', safe: 'bg-ok' };
  const CHIP = { bad: 'bg-bad-soft text-bad', warn: 'bg-warn-soft text-warn', neutral: 'bg-neutral-soft text-neutral' };
  const LEVEL_TEXT = { accent: 'text-accent', warn: 'text-warn', bad: 'text-bad' };
  type TileTone = 'bad' | 'warn' | 'accent' | 'ok';
  // Ikona kafelka dostaje kolor tylko wtedy, gdy jest co zgłosić; zero zostaje szare.
  const tiles = $derived([
    { icon: 'shield-x', value: counts.malicious, label: t('expert.malicious'), tone: 'bad' },
    { icon: 'shield-alert', value: counts.suspicious, label: t('expert.suspicious'), tone: 'warn' },
    { icon: 'download', value: counts.non_play, label: t('expert.non_play'), tone: 'accent' },
    { icon: 'shield-user', value: counts.admins, label: t('expert.admins'), tone: 'accent' },
  ] as { icon: IconName; value: number; label: string; tone: TileTone }[]);
  const NUMBER = { bad: 'text-bad', warn: 'text-warn', accent: '', ok: 'text-ok' };
  const TILE_ICON = {
    bad: 'bg-bad-soft text-bad', warn: 'bg-warn-soft text-warn', accent: 'bg-accent-soft text-accent',
    ok: 'bg-ok-soft text-ok',
  };
  const TILE_ICON_OFF = 'bg-neutral-soft text-soft ring-1 ring-current/15 ring-inset';

  // Wybrana opcja zostaje na liście z zerem, gdy przełącznik lub wyszukiwarka ją ukryje.
  const typeChips = $derived([...facets.categories, ...s.categoryFilter
    .filter((c) => !facets.categories.some((f) => f.value === c)).map((value) => ({ value, count: 0 }))]);
  const sourceOptions = $derived(s.sourceFilter && !facets.sources.some((f) => f.value === s.sourceFilter)
    ? [...facets.sources, { value: s.sourceFilter, count: 0 }] : facets.sources);
  const filtered = $derived(s.categoryFilter.length > 0 || s.sourceFilter !== null);

  function toggleType(c: Category) {
    s.categoryFilter = s.categoryFilter.includes(c) ? s.categoryFilter.filter((x) => x !== c) : [...s.categoryFilter, c];
  }

  function clearFilters() {
    s.categoryFilter = [];
    s.sourceFilter = null;
  }

  let table: HTMLElement;

  async function keydown(e: KeyboardEvent) {
    if (e.target !== e.currentTarget) return; // klawisze w polach wiersza należą do tych pól
    const ids = rows.map((r) => r.package);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      ctl.focus(moveFocus(ids, focused, e.key === 'ArrowDown' ? 1 : -1));
      await tick();
      table.querySelector('tr[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === ' ' && focused) {
      e.preventDefault();
      const app = rows.find((r) => r.package === focused);
      if (app) ctl.toggle(app);
    }
  }

  function when(days: number | null): string {
    if (days === null) return '';
    return days === 0 ? t('expert.today') : tp('expert.days', days);
  }
</script>

<div class="grid grid-cols-5 gap-3">
  {#each tiles as tile (tile.icon)}
    <div class="relative rounded-2xl card px-4 py-3">
      <span class="absolute top-3 right-3 grid h-8 w-8 place-items-center rounded-[10px]
        {tile.value > 0 ? `${TILE_ICON[tile.tone]} glow-soft` : TILE_ICON_OFF}" aria-hidden="true"><Icon name={tile.icon} size={17} /></span>
      <b class="block text-2xl {tile.value > 0 ? NUMBER[tile.tone] : ''}"><CountUp value={tile.value} /></b>
      <span class="text-2xs text-mut">{tile.label}</span>
    </div>
  {/each}
  <div class="relative rounded-2xl card px-4 py-3" title={collectors.failed.map((c) => t('expert.collector_failed', { name: c.name, error: c.error ?? '' })).join('\n')}>
    <span class="absolute top-3 right-3 grid h-8 w-8 place-items-center rounded-[10px]
      {complete ? TILE_ICON.ok : TILE_ICON.warn} glow-soft" aria-hidden="true"><Icon name="scan-search" size={17} /></span>
    <b class="mono block text-xl {complete ? 'text-ok' : 'text-warn'}">{collectors.ok}/{collectors.total}</b>
    <span class="text-2xs text-mut">{apk ? t('expert.collectors_apk', { ok: collectors.ok, total: collectors.total, analyzed: apk.analyzed, requested: apk.requested }) : t('expert.collectors_only', { ok: collectors.ok, total: collectors.total })}</span>
  </div>
</div>

<div class="flex items-center gap-3">
  <Segmented label={t('expert.filter')} value={s.showAll ? 'all' : 'attention'} options={filters}
    onchange={(v) => (s.showAll = v === 'all')} />
  <label class="field flex flex-1 items-center gap-2.5 rounded-xl px-3.5 py-2 text-soft">
    <Icon name="search" />
    <input type="search" class="flex-1 bg-transparent text-ink outline-none" bind:value={s.query}
      placeholder={t('expert.search')} aria-label={t('expert.search')} />
  </label>
</div>

<div class="flex flex-wrap items-center gap-2">
  <div role="group" aria-label={t('expert.filter_types')} class="flex flex-1 flex-wrap gap-1.5">
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
    {#each sourceOptions as o (o.value)}
      <option value={o.value}>{o.value} · {o.count}</option>
    {/each}
  </select>
</div>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div role="group" aria-label={t('expert.table')} tabindex="0" onkeydown={keydown} bind:this={table}
  class="flex-none overflow-hidden rounded-2xl card">
  <table class="w-full border-collapse">
    <thead>
      <tr class="bg-surface-2/60 text-left text-xs font-bold text-mut">
        <th class="w-10 border-b border-line px-4 py-3"></th>
        <th class="border-b border-line px-3 py-3">{t('expert.col_app')}</th>
        <th class="border-b border-line px-3 py-3">{t('expert.col_score')}</th>
        <th class="border-b border-line px-3 py-3">{t('expert.col_problems')}</th>
        <th class="border-b border-line px-3 py-3">{t('expert.col_source')}</th>
        <th class="border-b border-line px-3 py-3">{t('expert.col_action')}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as a (a.package)}
        {@const level = s.selection[a.package] ?? null}
        <tr aria-selected={a.package === focused} onclick={() => ctl.focus(a.package)}
          class="cursor-pointer border-b border-[var(--color-surface-2)] {a.package === focused ? 'bg-accent-soft/70 shadow-[inset_3px_0_0_var(--color-accent),inset_0_0_24px_-12px_var(--glow-accent)]' : 'hover:bg-surface-2'} {s.apk.changed.includes(a.package) ? 'flash' : ''}">
          <td class="px-4 py-3"><input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={level !== null} aria-label={a.package}
            onclick={(e) => e.stopPropagation()} onchange={() => ctl.toggle(a)} /></td>
          <td class="w-full max-w-0 px-3 py-3">
            <div class="flex items-center gap-3">
              <AppIcon icon={a.icon} class="h-8 w-8">
                <span class="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-sm font-extrabold text-white shadow-[inset_0_1px_0_rgb(255_255_255/.3)] {BAR[a.verdict]}" aria-hidden="true">{initial(a.name)}</span>
              </AppIcon>
              <div class="min-w-0"><b class="block truncate">{a.name}</b><span class="mono block truncate text-2xs text-soft">{a.package}</span></div>
            </div>
          </td>
          <td class="px-3 py-3 whitespace-nowrap"><div class="flex items-center gap-2">
            <b class="mono {SCORE[a.verdict]}">{a.score}</b>
            <span class="h-1.5 w-12 overflow-hidden rounded-full bg-neutral-soft shadow-[var(--shadow-well)]"><i class="block h-full rounded-full {BAR[a.verdict]}" style="width: {a.score}%"></i></span>
          </div></td>
          <td class="px-3 py-3"><span class="inline-flex gap-1">
            {#each a.symptoms as sy (sy.category)}
              <span class="grid h-6 w-6 place-items-center rounded-[7px] ring-1 ring-current/15 ring-inset {CHIP[sy.severity]}" title={t(categoryKey(sy.category))}>
                <Icon name={CATEGORY_ICON[sy.category]} size={14} />
              </span>
            {/each}
          </span></td>
          <td class="px-3 py-3 whitespace-nowrap">{a.source.label}<span class="block text-2xs text-soft">{when(a.source.days)}</span></td>
          <td class="px-3 py-3">
            <select aria-label="{t('expert.col_action')} {a.package}" value={level ?? ''} onclick={(e) => e.stopPropagation()}
              onchange={(e) => ctl.setLevel(a.package, (e.currentTarget.value || null) as Level | null)}
              class="field rounded-[10px] px-2.5 py-1.5 text-sm font-bold {level ? LEVEL_TEXT[LEVEL_TONE[level]] : 'text-mut'}">
              <option value="">{t('level.none')}</option>
              <option value="silence">{t('choice.silence')}</option>
              <option value="disable">{t('choice.disable')}</option>
              <option value="remove">{t('choice.remove')}</option>
            </select>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if rows.length === 0 && filtered}
    <div class="flex items-center justify-center gap-3 px-4 py-6 text-sm text-mut">
      {t('expert.no_match')}
      <button type="button" class="font-semibold text-accent hover:underline" onclick={clearFilters}>{t('expert.clear_filters')}</button>
    </div>
  {/if}
</div>
