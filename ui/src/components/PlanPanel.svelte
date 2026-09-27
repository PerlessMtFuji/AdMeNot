<script lang="ts">
  import { getContext } from 'svelte';
  import { flip } from 'svelte/animate';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { flaggedApps, LEVEL_TONE, planEntries } from '../lib/logic';
  import { DUR, enter, ms } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import DeviceCard from './DeviceCard.svelte';

  let { showSafe, ontoggleSafe }: { showSafe: boolean; ontoggleSafe: () => void } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const apps = $derived(s.scan?.apps ?? []);
  const entries = $derived(planEntries(apps, s.selection));
  const unchanged = $derived(flaggedApps(apps).filter((a) => !(a.package in s.selection)));
  const details = $derived(s.device
    ? `${s.device.model} · Android ${s.device.android}${s.device.patch ? ` · ${t('phone.patch')} ${s.device.patch}` : ''}`
    : '');
  const DOT = { accent: 'bg-accent', warn: 'bg-warn-strong', bad: 'bg-bad' };
</script>

{#if s.device}
  <DeviceCard compact name={s.device.name} {details} serial={s.device.serial} image={s.device.image} connected />
  <div class="h-px bg-line"></div>
{/if}
<span class="lbl">{t('panel.plan')}</span>
{#if entries.length === 0}<p class="text-mut">{t('panel.empty')}</p>{/if}
<ul class="flex flex-col gap-1.5">
  {#each entries as e (e.package)}
    <li animate:flip={{ duration: ms(DUR.flip) }} transition:enter
      class="flex items-center gap-2 rounded-[10px] bg-surface-2 px-2.5 py-2">
      <span class="h-2 w-2 flex-none rounded-full {DOT[LEVEL_TONE[e.level]]}"></span>
      <b class="min-w-0 flex-1 truncate">{e.name}</b>
      <Pill tone={LEVEL_TONE[e.level]}>{t(`choice.${e.level}`)}</Pill>
    </li>
  {/each}
</ul>
{#each unchanged as a (a.package)}<p class="text-[11px] text-soft">{a.name} — {t('panel.unchanged')}</p>{/each}
{#if s.scan && s.scan.counts.safe > 0}
  <button type="button" aria-expanded={showSafe} onclick={ontoggleSafe}
    class="flex items-center gap-2.5 rounded-xl bg-ok-soft px-3 py-2.5 text-left">
    <span class="grid h-[22px] w-[22px] flex-none place-items-center rounded-full bg-ok text-white"><Icon name="check" size={12} strokeWidth={3} /></span>
    <span><b class="block">{tp('results.safe', s.scan.counts.safe)}</b>
      <span class="text-[11px] font-semibold text-accent">{showSafe ? t('results.safe_hide') : t('results.safe_show')}</span></span>
  </button>
{/if}
<div class="mt-auto text-[11px] text-mut">{t('plan.undo_hint')}</div>
<Button variant="primary" size="lg" disabled={entries.length === 0 || s.orderRunning} onclick={() => ctl.openPlan()}>
  {t('actions.fix', { count: entries.length })}
</Button>
