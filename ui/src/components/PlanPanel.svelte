<script lang="ts">
  import { getContext } from 'svelte';
  import { flip } from 'svelte/animate';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { flaggedApps, groupOpen, LEVEL_TONE, planEntries } from '../lib/logic';
  import { DUR, enter, ms } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import DeviceCard from './DeviceCard.svelte';
  import MirrorControls from './MirrorControls.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const safeOpen = $derived(groupOpen('safe', s.settings.mode, s.openGroups, false));
  // Rozwija/zwija sekcję „Bez uwag” i przewija do niej po rozwinięciu.
  function showSafe() {
    const opening = !safeOpen;
    ctl.setGroupOpen('safe', opening);
    if (opening) requestAnimationFrame(() => document.getElementById('group-safe')?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
  }
  const apps = $derived(s.scan?.apps ?? []);
  const entries = $derived(planEntries(apps, s.selection));
  const safeIncomplete = $derived(apps.filter((a) => a.verdict === 'safe' && a.incomplete).length);
  const unchanged = $derived(flaggedApps(apps).filter((a) => !(a.package in s.selection)));
  const details = $derived(s.device
    ? `${s.device.model} · Android ${s.device.android}${s.device.patch ? ` · ${t('phone.patch')} ${s.device.patch}` : ''}`
    : '');
  const DOT = { accent: 'bg-accent text-accent', warn: 'bg-warn-strong text-warn-strong', bad: 'bg-bad text-bad' };
</script>

{#if s.device}
  <DeviceCard compact name={s.device.name} {details} serial={s.device.serial} imei={s.device.imei} image={s.device.image} connected>
    <MirrorControls serial={s.device.serial} name={s.device.name} />
  </DeviceCard>
  <div class="h-px bg-line"></div>
{/if}
<span class="lbl">{t('panel.plan')}</span>
{#if entries.length === 0}<p class="text-mut">{t('panel.empty')}</p>{/if}
<ul class="well well-list flex flex-col overflow-hidden empty:hidden">
  {#each entries as e (e.package)}
    <li animate:flip={{ duration: ms(DUR.flip) }} transition:enter
      class="flex items-center gap-2.5 px-3.5 py-2.5">
      <span class="glow-dot h-2 w-2 flex-none rounded-full {DOT[LEVEL_TONE[e.level]]}"></span>
      <b class="min-w-0 flex-1 truncate">{e.name}</b>
      <Pill tone={LEVEL_TONE[e.level]}>{t(`choice.${e.level}`)}</Pill>
    </li>
  {/each}
</ul>
{#each unchanged as a (a.package)}<p class="text-xs text-soft">{a.name} — {t('panel.unchanged')}</p>{/each}
{#if s.scan && s.scan.counts.safe > 0}
  <button type="button" aria-expanded={safeOpen} onclick={showSafe}
    class="flex items-center gap-3 rounded-2xl bg-ok-soft px-4 py-3 text-left ring-1 ring-ok/20 ring-inset transition duration-150 hover:ring-ok/40">
    {#if safeIncomplete}
      <span class="grid h-7 w-7 flex-none place-items-center rounded-full bg-warn-strong text-white shadow-[0_0_14px_-2px_var(--color-warn-strong)]"><Icon name="info" size={15} strokeWidth={3} /></span>
    {:else}
      <span class="grid h-7 w-7 flex-none place-items-center rounded-full bg-ok text-white shadow-[0_0_14px_-2px_var(--color-ok)]"><Icon name="check" size={15} strokeWidth={3} /></span>
    {/if}
    <span><b class="block">{tp('results.safe', s.scan.counts.safe)}</b>
      {#if safeIncomplete}<span class="block text-xs font-semibold text-warn">{tp('results.safe_incomplete', safeIncomplete)}</span>{/if}
      <span class="text-xs font-semibold text-accent">{safeOpen ? t('results.safe_hide') : t('results.safe_show')}</span></span>
  </button>
{/if}
<div class="mt-auto text-xs text-mut">{t('plan.undo_hint')}</div>
<Button variant="primary" size="lg" disabled={entries.length === 0 || s.orderRunning} onclick={() => ctl.openPlan()}>
  {t('actions.fix', { count: entries.length })}
</Button>
