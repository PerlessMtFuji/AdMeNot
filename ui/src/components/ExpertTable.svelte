<script lang="ts">
  import { getContext } from 'svelte';
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { initial, LEVEL_TONE, moveFocus } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import CountUp from '../ui/CountUp.svelte';
  import Icon from '../ui/Icon.svelte';
  import Segmented from '../ui/Segmented.svelte';

  let { rows, focused }: { rows: AppView[]; focused: string | null } = $props();
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

  function keydown(e: KeyboardEvent) {
    const ids = rows.map((r) => r.package);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      ctl.focus(moveFocus(ids, focused, e.key === 'ArrowDown' ? 1 : -1));
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

<div class="grid grid-cols-5 gap-2">
  <div class="rounded-xl bg-surface px-3 py-2 shadow-card"><b class="block text-[18px] text-bad"><CountUp value={counts.malicious} /></b><span class="text-[10.5px] text-mut">{t('expert.malicious')}</span></div>
  <div class="rounded-xl bg-surface px-3 py-2 shadow-card"><b class="block text-[18px] text-warn"><CountUp value={counts.suspicious} /></b><span class="text-[10.5px] text-mut">{t('expert.suspicious')}</span></div>
  <div class="rounded-xl bg-surface px-3 py-2 shadow-card"><b class="block text-[18px]"><CountUp value={counts.non_play} /></b><span class="text-[10.5px] text-mut">{t('expert.non_play')}</span></div>
  <div class="rounded-xl bg-surface px-3 py-2 shadow-card"><b class="block text-[18px]"><CountUp value={counts.admins} /></b><span class="text-[10.5px] text-mut">{t('expert.admins')}</span></div>
  <div class="rounded-xl bg-surface px-3 py-2 shadow-card" title={collectors.failed.map((c) => t('expert.collector_failed', { name: c.name, error: c.error ?? '' })).join('\n')}>
    <b class="mono block text-[16px] {complete ? 'text-ok' : 'text-warn'}">{collectors.ok}/{collectors.total}</b>
    <span class="text-[10.5px] text-mut">{apk ? t('expert.collectors_apk', { ok: collectors.ok, total: collectors.total, analyzed: apk.analyzed, requested: apk.requested }) : t('expert.collectors_only', { ok: collectors.ok, total: collectors.total })}</span>
  </div>
</div>

<div class="flex items-center gap-2">
  <Segmented label={t('expert.filter')} value={s.showAll ? 'all' : 'attention'} options={filters}
    onchange={(v) => (s.showAll = v === 'all')} />
  <label class="flex flex-1 items-center gap-2 rounded-[10px] border border-line bg-surface px-3 py-1.5 text-soft">
    <Icon name="search" />
    <input type="search" class="flex-1 bg-transparent text-ink outline-none" bind:value={s.query}
      placeholder={t('expert.search')} aria-label={t('expert.search')} />
  </label>
</div>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div role="group" aria-label={t('expert.table')} tabindex="0" onkeydown={keydown}
  class="overflow-hidden rounded-2xl bg-surface shadow-card">
  <table class="w-full border-collapse">
    <thead>
      <tr class="text-left text-[10px] tracking-[.08em] text-mut uppercase">
        <th class="w-8 border-b border-line px-3 py-2"></th>
        <th class="border-b border-line px-3 py-2">{t('expert.col_app')}</th>
        <th class="border-b border-line px-3 py-2">{t('expert.col_score')}</th>
        <th class="border-b border-line px-3 py-2">{t('expert.col_problems')}</th>
        <th class="border-b border-line px-3 py-2">{t('expert.col_source')}</th>
        <th class="border-b border-line px-3 py-2">{t('expert.col_action')}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as a (a.package)}
        {@const level = s.selection[a.package] ?? null}
        <tr aria-selected={a.package === focused} onclick={() => ctl.focus(a.package)}
          class="cursor-pointer border-b border-[var(--color-surface-2)] {a.package === focused ? 'bg-accent-soft/60 shadow-[inset_3px_0_0_var(--color-accent)]' : 'hover:bg-surface-2'} {s.apk.changed.includes(a.package) ? 'flash' : ''}">
          <td class="px-3 py-2"><input type="checkbox" checked={level !== null} aria-label={a.package}
            onclick={(e) => e.stopPropagation()} onchange={() => ctl.toggle(a)} /></td>
          <td class="px-3 py-2">
            <div class="flex items-center gap-2">
              <span class="grid h-[26px] w-[26px] flex-none place-items-center rounded-lg text-[12px] font-extrabold text-white {BAR[a.verdict]}" aria-hidden="true">{initial(a.name)}</span>
              <div class="min-w-0"><b class="block truncate">{a.name}</b><span class="mono block truncate text-[10px] text-soft">{a.package}</span></div>
            </div>
          </td>
          <td class="px-3 py-2"><div class="flex items-center gap-2">
            <b class="mono {SCORE[a.verdict]}">{a.score}</b>
            <span class="h-[5px] w-14 overflow-hidden rounded bg-neutral-soft"><i class="block h-full {BAR[a.verdict]}" style="width: {a.score}%"></i></span>
          </div></td>
          <td class="px-3 py-2"><span class="inline-flex gap-[3px]">
            {#each a.symptoms as sy (sy.category)}
              <span class="grid h-[22px] w-[22px] place-items-center rounded-[7px] {CHIP[sy.severity]}" title={t(categoryKey(sy.category))}>
                <Icon name={CATEGORY_ICON[sy.category]} size={13} />
              </span>
            {/each}
          </span></td>
          <td class="px-3 py-2">{a.source.label}<span class="block text-[10px] text-soft">{when(a.source.days)}</span></td>
          <td class="px-3 py-2">
            <select aria-label="{t('expert.col_action')} {a.package}" value={level ?? ''} onclick={(e) => e.stopPropagation()}
              onchange={(e) => ctl.setLevel(a.package, (e.currentTarget.value || null) as Level | null)}
              class="rounded-lg border border-line bg-surface px-2 py-1 text-[11px] font-bold {level ? LEVEL_TEXT[LEVEL_TONE[level]] : 'text-mut'}">
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
