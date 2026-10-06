<script lang="ts">
  import { getContext, tick } from 'svelte';
  import { categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { groupOpen, initial, LEVEL_TONE, moveFocus, topReasons } from '../lib/logic';
  import type { AppView, Category, Level, Verdict } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import AppIcon from './AppIcon.svelte';
  import FiltersMenu from './FiltersMenu.svelte';
  import VerdictSection from './VerdictSection.svelte';

  type Facets = { categories: { value: Category; count: number }[]; sources: { value: string; count: number }[]; nonPlay: number };
  type Group = { verdict: Verdict; apps: AppView[] };
  let { groups, focused, facets, searching, navRows }:
    { groups: Group[]; focused: string | null; facets: Facets; searching: boolean; navRows: AppView[] } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const SCORE = { malicious: 'text-bad', suspicious: 'text-warn', review: 'text-neutral', safe: 'text-ok' };
  const BAR = { malicious: 'bg-bad', suspicious: 'bg-warn-strong', review: 'bg-soft', safe: 'bg-ok' };
  const LEVEL_TEXT = { accent: 'text-accent', warn: 'text-warn', bad: 'text-bad' };
  // Groźne sekcje są zawsze otwarte; reszta według zapisu lub (przy wyszukiwaniu) sama się rozwija.
  const DANGER: Verdict[] = ['malicious', 'suspicious'];
  const isOpen = (v: Verdict) => groupOpen(v, s.settings.mode, s.openGroups, searching);
  // Puste linie „Szkodliwe 0 — nic nie znaleziono” tylko gdy coś jest oznaczone; na czystym telefonie zostaje samo „Bez uwag”.
  const anyFlagged = $derived(groups.some((g) => g.verdict !== 'safe' && g.apps.length > 0));
  const shown = $derived(groups.filter((g) => g.apps.length > 0 || (!searching && anyFlagged && DANGER.includes(g.verdict))));
  const firstWithRows = $derived(shown.find((g) => g.apps.length > 0 && isOpen(g.verdict))?.verdict ?? null);
  const total = $derived(s.scan!.counts.total);
  const reason = (a: AppView) => topReasons(a, 1, (c) => t(categoryKey(c)));
  const filtered = $derived(s.categoryFilter.length > 0 || s.sourceFilter !== null);

  function clearFilters() {
    s.categoryFilter = [];
    s.sourceFilter = null;
  }

  let table: HTMLElement;

  async function keydown(e: KeyboardEvent) {
    if (e.target !== e.currentTarget) return; // klawisze w polach wiersza należą do tych pól
    const ids = navRows.map((r) => r.package);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      ctl.focus(moveFocus(ids, focused, e.key === 'ArrowDown' ? 1 : -1));
      await tick();
      table.querySelector('tr[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === ' ' && focused) {
      e.preventDefault();
      const app = navRows.find((r) => r.package === focused);
      if (app) ctl.toggle(app);
    }
  }

  function when(days: number | null): string {
    if (days === null) return '';
    return days === 0 ? t('expert.today') : tp('expert.days', days);
  }
</script>

<div class="flex items-center gap-3">
  <label class="field flex flex-1 items-center gap-2.5 rounded-xl px-3.5 py-2 text-soft">
    <Icon name="search" />
    <input type="search" class="flex-1 bg-transparent text-ink outline-none" bind:value={s.query}
      placeholder={t('expert.search_in', { count: total })} aria-label={t('expert.search')} />
  </label>
  <FiltersMenu {facets} />
</div>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div role="group" aria-label={t('expert.table')} tabindex="0" onkeydown={keydown} bind:this={table} class="flex flex-col gap-4 outline-none">
  {#each shown as g (g.verdict)}
    <VerdictSection verdict={g.verdict} count={g.apps.length} open={isOpen(g.verdict)}
      collapsible={!searching && g.apps.length > 0 && !DANGER.includes(g.verdict)}
      ontoggle={() => ctl.setGroupOpen(g.verdict, !isOpen(g.verdict))}>
      <div class="flex-none overflow-hidden rounded-2xl card">
        <table class="w-full table-fixed border-collapse">
          <colgroup>
            <col class="w-10" /><col /><col class="w-[21%]" /><col class="w-[100px]" /><col class="w-[96px]" /><col class="w-[120px]" />
          </colgroup>
          {#if g.verdict === firstWithRows}
            <thead>
              <tr class="bg-surface-2/60 text-left text-xs font-bold text-mut">
                <th class="border-b border-line px-3 py-3"></th>
                <th class="border-b border-line px-3 py-3">{t('expert.col_app')}</th>
                <th class="border-b border-line px-3 py-3">{t('expert.col_reason')}</th>
                <th class="border-b border-line px-3 py-3">{t('expert.col_score')}</th>
                <th class="border-b border-line px-3 py-3">{t('expert.col_source')}</th>
                <th class="border-b border-line px-3 py-3">{t('expert.col_action')}</th>
              </tr>
            </thead>
          {/if}
          <tbody>
            {#each g.apps as a (a.package)}
              {@const r = reason(a)}
        {@const level = s.selection[a.package] ?? null}
        {@const done = s.acted[a.package] ?? null}
        <tr aria-selected={a.package === focused} onclick={() => ctl.focus(a.package)}
          class="cursor-pointer border-b border-[var(--color-surface-2)] {a.package === focused ? 'bg-accent-soft/70 shadow-[inset_3px_0_0_var(--color-accent),inset_0_0_24px_-12px_var(--glow-accent)]' : 'hover:bg-surface-2'} {s.apk.changed.includes(a.package) ? 'flash' : ''}">
          <td class="px-3 py-3"><input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={level !== null} disabled={done === 'remove'} aria-label={a.package}
            onclick={(e) => e.stopPropagation()} onchange={() => ctl.toggle(a)} /></td>
          <td class="px-3 py-3">
            <div class="flex items-center gap-3">
              <AppIcon icon={a.icon} class="h-8 w-8">
                <span class="grid h-8 w-8 flex-none place-items-center rounded-[10px] text-sm font-extrabold text-white shadow-[inset_0_1px_0_rgb(255_255_255/.3)] {BAR[a.verdict]}" aria-hidden="true">{initial(a.name)}</span>
              </AppIcon>
              <div class="min-w-0"><b class="block truncate">{a.name}</b><span class="mono block truncate text-2xs text-soft">{a.package}{#if done} · <span class="text-ok">{t(`history.level_done.${done}`)}</span>
                · <button type="button" class="font-sans font-semibold text-accent hover:underline disabled:opacity-50" disabled={s.orderRunning}
                  aria-label={t('summary.undo_app', { name: a.name })} onclick={(e) => { e.stopPropagation(); void ctl.undoApp(a.package); }}>{t('history.undo_changes')}</button>{/if}</span></div>
            </div>
          </td>
          <td class="px-3 py-3 text-sm"><span class="line-clamp-2">{r.items[0]?.label ?? ''}</span>
            {#if r.more.length}<span data-more class="text-xs text-soft" title={r.more.map((c) => t(categoryKey(c))).join(', ')}>+{r.more.length}</span>{/if}</td>
          <td class="px-3 py-3 whitespace-nowrap"><div class="flex items-center gap-2">
            <b class="mono {SCORE[a.verdict]}">{a.score}</b>
            <span class="h-1.5 w-12 overflow-hidden rounded-full bg-neutral-soft shadow-[var(--shadow-well)]"><i class="block h-full rounded-full {BAR[a.verdict]}" style="width: {a.score}%"></i></span>
          </div></td>
          <td class="px-3 py-3 whitespace-nowrap">{a.source.label}<span class="block text-2xs text-soft">{when(a.source.days)}</span></td>
          <td class="px-3 py-3">
            <select aria-label="{t('expert.col_action')} {a.package}" value={level ?? ''} disabled={done === 'remove'} onclick={(e) => e.stopPropagation()}
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
      </div>
    </VerdictSection>
  {/each}
  {#if !shown.some((g) => g.apps.length) && filtered}
    <div class="flex items-center justify-center gap-3 rounded-2xl card px-4 py-6 text-sm text-mut">
      {t('expert.no_match')}
      <button type="button" class="font-semibold text-accent hover:underline" onclick={clearFilters}>{t('expert.clear_filters')}</button>
    </div>
  {/if}
</div>
