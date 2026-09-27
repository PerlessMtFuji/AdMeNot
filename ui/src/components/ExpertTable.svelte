<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { levelTag, signalChips, sourceKey, verdictColor, visibleApps } from '../lib/logic';
  import type { Level } from '../lib/types';
  import EvidencePanel from './EvidencePanel.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const VERDICTS = ['all', 'malicious', 'suspicious', 'review', 'safe'] as const;
  const counts = $derived(s.scan!.counts);
  const collectors = $derived(s.scan!.collectors);
  const rows = $derived(visibleApps(s.scan!.apps,
    { showAll: s.showAll, verdict: s.verdictFilter, query: s.query }));
</script>

<div class="grid grid-cols-5 gap-2">
  <div class="card py-2"><b class="block text-[18px] text-[#b91c1c]">{counts.malicious}</b><span class="text-[10px] text-mut">{t('expert.malicious')}</span></div>
  <div class="card py-2"><b class="block text-[18px] text-[#92400e]">{counts.suspicious}</b><span class="text-[10px] text-mut">{t('expert.suspicious')}</span></div>
  <div class="card py-2"><b class="block text-[18px]">{counts.non_play}</b><span class="text-[10px] text-mut">{t('expert.non_play')}</span></div>
  <div class="card py-2"><b class="block text-[18px]">{counts.admins}</b><span class="text-[10px] text-mut">{t('expert.admins')}</span></div>
  <div class="card py-2"><b class="mono block pt-1 text-[14px]">{collectors.ok}/{collectors.total}</b><span class="text-[10px] text-mut">{t('expert.collectors')}</span></div>
</div>

{#each collectors.failed as c (c.name)}
  <div class="mono text-[11px] warn">⚠ {t('expert.collector_failed', { name: c.name, error: c.error ?? '' })}</div>
{/each}

<div class="flex flex-wrap items-center gap-3">
  <select class="rounded border border-line bg-card px-1.5 py-1" bind:value={s.verdictFilter} aria-label={t('verdict.all')}>
    {#each VERDICTS as v (v)}<option value={v}>{t(`verdict.${v}`)}</option>{/each}
  </select>
  <input type="search" class="flex-1 rounded border border-line bg-card px-2 py-1" bind:value={s.query}
    placeholder={t('expert.search')} aria-label={t('expert.search')} />
  <label class="flex items-center gap-1.5"><input type="checkbox" bind:checked={s.showAll} /> {t('expert.show_all')}</label>
</div>

<table class="w-full border-collapse overflow-hidden rounded-[9px] border border-line bg-card text-[11px]">
  <thead>
    <tr class="bg-[#f5f8fb] text-left text-[10px] tracking-[.08em] text-mut uppercase">
      <th class="p-1.5"></th>
      <th class="p-1.5">{t('expert.col_app')}</th>
      <th class="p-1.5">{t('expert.col_score')}</th>
      <th class="p-1.5">{t('expert.col_signals')}</th>
      <th class="p-1.5">{t('expert.col_source')}</th>
      <th class="p-1.5">{t('expert.col_action')}</th>
    </tr>
  </thead>
  <tbody>
    {#each rows as a (a.package)}
      {@const level = s.selection[a.package] ?? null}
      <tr class="border-b border-[#e5ebf1] align-top {s.apk.changed.includes(a.package) ? 'flash' : ''}">
        <td class="p-1.5"><input type="checkbox" checked={level !== null} aria-label={a.package} onchange={() => ctl.toggle(a)} /></td>
        <td class="p-1.5">
          <button class="text-left" aria-expanded={s.expanded.includes(a.package)} onclick={() => ctl.toggleExpanded(a.package)}>
            <b>{a.name}</b><br /><span class="mono text-mut">{a.package}</span>
          </button>
          {#if s.expanded.includes(a.package)}<EvidencePanel app={a} />{/if}
        </td>
        <td class="mono p-1.5">
          <b>{a.score}</b>
          <div class="mt-0.5 h-[5px] w-[60px] overflow-hidden rounded bg-[#e5ebf1]">
            <i class="block h-full" style="width: {a.score}%; background: {verdictColor(a.verdict)}"></i>
          </div>
        </td>
        <td class="p-1.5">
          {#each signalChips(a) as chip (chip.label)}<span class="chip {chip.bad ? 'chip-bad' : ''}">{chip.label}</span>{/each}
          {#if a.apk_error}<span class="chip">{t('expert.apk_error')}</span>{/if}
        </td>
        <td class="mono p-1.5">
          {t(`expert.source_${sourceKey(a)}`)}
          {#if a.installer && !a.from_play && !a.is_system}<br /><span class="text-mut">{a.installer}</span>{/if}
        </td>
        <td class="p-1.5">
          <select class="tag {levelTag(level)}" aria-label="{t('expert.col_action')} {a.package}" value={level ?? ''}
            onchange={(e) => ctl.setLevel(a.package, (e.currentTarget.value || null) as Level | null)}>
            <option value="">{t('level.none')}</option>
            <option value="silence">{t('level.silence')}</option>
            <option value="disable">{t('level.disable')}</option>
            <option value="remove">{t('level.remove')}</option>
          </select>
        </td>
      </tr>
    {/each}
  </tbody>
</table>
