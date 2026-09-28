<script lang="ts">
  import { getContext } from 'svelte';
  import { slide } from 'svelte/transition';
  import AdminPrompt from '../components/AdminPrompt.svelte';
  import AppIcon from '../components/AppIcon.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import ReportButton from '../components/ReportButton.svelte';
  import StepTimeline from '../components/StepTimeline.svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { groupSteps, initial, LEVEL_TONE } from '../lib/logic';
  import { DUR, enter, ms, pop } from '../lib/motion';
  import type { Level, OrderResult } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Progress from '../ui/Progress.svelte';
  import SidePanel from '../ui/SidePanel.svelte';

  type AppResult = OrderResult['apps'][number];
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const groups = $derived(groupSteps(s.steps));
  const planned = $derived((s.execPlan?.apps ?? []).filter((a) => !a.blocked));
  const running = $derived(s.phase === 'executing');
  const waiting = $derived(running ? planned.filter((a) => !groups.some((g) => g.package === a.package)) : []);
  const total = $derived(planned.reduce((n, a) => n + a.steps.length, 0) || s.steps.length);
  const finished = $derived(s.steps.filter((x) => x.status !== 'running').length);
  const results = $derived(new Map((s.result?.apps ?? []).map((a) => [a.package, a])));
  const orphans = $derived((s.result?.apps ?? []).filter((a) => !groups.some((g) => g.package === a.package)));
  const allOk = $derived(s.result !== null && s.result.apps.every((a) => a.outcome === 'ok'));
  const TONE = { ok: 'text-ok', warn: 'text-warn', bad: 'text-bad' };
  const icons = $derived(new Map((s.scan?.apps ?? []).map((a) => [a.package, a.icon])));

  function levelOf(pkg: string): Level | null {
    return planned.find((a) => a.package === pkg)?.level ?? null;
  }

  function outcome(app: AppResult): { text: string; tone: 'ok' | 'warn' | 'bad' } {
    const level = levelOf(app.package);
    switch (app.outcome) {
      case 'ok':
        return { text: level ? t(`result.ok_level.${level}`) : t('result.ok'), tone: 'ok' };
      case 'still_active':
        return { text: t('result.still_active', { kinds: app.kinds.join(', ') }), tone: 'warn' };
      case 'stopped':
        return { text: t('result.stopped'), tone: 'warn' };
      default:
        return { text: `${t('result.failed')}: ${app.errors.join('; ')}`, tone: 'bad' };
    }
  }

  function panelState(pkg: string): string {
    const res = results.get(pkg);
    if (res) return t(`exec.state.${res.outcome === 'ok' ? 'ok' : res.outcome}`);
    return groups.some((g) => g.package === pkg) ? t('exec.state.running') : t('exec.state.queued');
  }

  async function undoAll(order: string) {
    await ctl.openHistory(s.device?.serial ?? null);
    await ctl.undo(order);
  }
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-3 scroll-fade overflow-auto px-7 py-7">
    {#if s.result}
      <div class="flex flex-col items-center gap-1.5 py-5 text-center">
        {#if s.result.stopped}
          <span class="grid h-20 w-20 place-items-center rounded-full bg-warn-strong text-white shadow-[0_0_0_12px_var(--color-warn-soft),0_0_40px_-4px_var(--color-warn-strong)]" in:pop><Icon name="pause" size={36} /></span>
          <h1 class="mt-2.5 text-2xl font-extrabold">{t('exec.stopped_title')}</h1>
          <p class="text-mut">{t('exec.stopped')}</p>
        {:else}
          <span class="grid h-20 w-20 place-items-center rounded-full text-white {allOk ? 'bg-ok shadow-[0_0_0_12px_var(--color-ok-soft),0_0_40px_-4px_var(--color-ok)]' : 'bg-warn-strong shadow-[0_0_0_12px_var(--color-warn-soft),0_0_40px_-4px_var(--color-warn-strong)]'}" in:pop>
            <Icon name={allOk ? 'check' : 'triangle-alert'} size={38} strokeWidth={3} />
          </span>
          <h1 class="mt-2.5 text-2xl font-extrabold">{allOk ? t('exec.done_title') : t('exec.done_warn')}</h1>
          <p class="text-mut">{t('exec.done_sub', { apps: tp('exec.apps', s.result.apps.length), steps: tp('exec.steps', finished) })}</p>
        {/if}
      </div>
    {:else}
      <header>
        <div class="flex items-end gap-3">
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-semibold text-soft">{[s.client.trim(), s.order].filter(Boolean).join(' · ')}</div>
            <h1 class="text-2xl font-extrabold">{t('exec.title')}</h1>
          </div>
          <span class="text-sm text-soft tabular-nums">{t('exec.step', { done: Math.min(finished + 1, total), total })}</span>
        </div>
        <div class="mt-3"><Progress value={total ? finished / total : 0} label={t('exec.title')} /></div>
      </header>
    {/if}

    <AdminPrompt />
    {#if s.verifying}<Banner tone="info" icon="info" title={t('exec.verifying')} />{/if}

    {#each groups as g (g.package)}
      {@const res = results.get(g.package)}
      {@const level = levelOf(g.package)}
      <Card role="article" label={g.name}>
        <div class="flex items-center gap-3 px-5 py-3.5">
          <AppIcon icon={icons.get(g.package)} class="h-9 w-9"><span class="grid h-9 w-9 flex-none place-items-center rounded-[11px] bg-neutral-soft font-extrabold text-mut shadow-[var(--shadow-well)]" aria-hidden="true">{initial(g.name)}</span></AppIcon>
          <b class="min-w-0 flex-1 truncate">{g.name}</b>
          {#if res}
            {@const o = outcome(res)}
            <span class="text-sm font-bold {TONE[o.tone]}" in:enter>{o.text}</span>
          {:else if level}
            <Pill tone={LEVEL_TONE[level]}>{t(`choice.${level}`)}</Pill>
          {/if}
        </div>
        {#if !res || res.outcome !== 'ok'}
          <div transition:slide={{ duration: ms(DUR.enter) }}><StepTimeline steps={g.steps} /></div>
        {/if}
      </Card>
    {/each}
    {#each orphans as res (res.package)}
      {@const o = outcome(res)}
      {@const level = levelOf(res.package)}
      <Card role="article" label={res.name}>
        <div class="flex items-center gap-3 px-5 py-3.5">
          <AppIcon icon={icons.get(res.package)} class="h-9 w-9"><span class="grid h-9 w-9 flex-none place-items-center rounded-[11px] bg-neutral-soft font-extrabold text-mut shadow-[var(--shadow-well)]" aria-hidden="true">{initial(res.name)}</span></AppIcon>
          <b class="min-w-0 flex-1 truncate">{res.name}</b>
          {#if level}<Pill tone={LEVEL_TONE[level]}>{t(`choice.${level}`)}</Pill>{/if}
          <span class="text-sm font-bold {TONE[o.tone]}">{o.text}</span>
        </div>
      </Card>
    {/each}
    {#each waiting as a (a.package)}
      <Card dim role="article" label={a.name}>
        <div class="flex items-center gap-3 px-5 py-3.5">
          <AppIcon icon={icons.get(a.package)} class="h-9 w-9"><span class="grid h-9 w-9 flex-none place-items-center rounded-[11px] bg-neutral-soft font-extrabold text-mut shadow-[var(--shadow-well)]" aria-hidden="true">{initial(a.name)}</span></AppIcon>
          <b class="min-w-0 flex-1 truncate">{a.name}</b>
          <span class="text-soft">{t('exec.waiting')}</span>
          <Pill tone={LEVEL_TONE[a.level]}>{t(`choice.${a.level}`)}</Pill>
        </div>
      </Card>
    {/each}
  </main>

  <SidePanel label={t('exec.panel')}>
    {#if s.device}
      <DeviceCard compact name={s.device.name} details={`Android ${s.device.android}`} serial={s.device.serial}
        image={s.device.image} connected={running} />
      <div class="h-px bg-line"></div>
    {/if}
    <span class="lbl">{t('exec.panel')}</span>
    <ul class="well well-list flex flex-col overflow-hidden empty:hidden">
      {#each planned as a (a.package)}
        {@const res = results.get(a.package)}
        <li class="flex items-center gap-2.5 px-3.5 py-2.5 transition-colors duration-300
          {!res && groups.some((g) => g.package === a.package) ? 'bg-accent-soft' : ''}">
          <b class="min-w-0 flex-1 truncate">{a.name}</b>
          <span class="text-xs font-semibold {res ? TONE[outcome(res).tone] : 'text-accent'}">{panelState(a.package)}</span>
        </li>
      {/each}
    </ul>
    {#if running}
      <p class="mt-auto text-xs text-mut">{t('exec.stop_hint')}</p>
      <Button disabled={s.stopping || !s.job} onclick={() => ctl.stop()}>
        <Icon name="pause" />{s.stopping ? t('exec.stopping') : t('exec.stop')}
      </Button>
    {:else if s.result}
      {@const order = s.result.order}
      <div class="mt-auto flex flex-col gap-2">
        {#if s.result.stopped}
          <Button variant="primary" size="lg" disabled={s.orderRunning} onclick={() => ctl.resume(order)}>{t('exec.resume')}</Button>
        {/if}
        <Button variant={s.result.stopped ? 'secondary' : 'primary'} size="lg" onclick={() => ctl.newScan()}>{t('exec.new_scan')}</Button>
        <ReportButton order={order} size="lg" />
        <Button variant="ghost" disabled={s.orderRunning} onclick={() => undoAll(order)}><Icon name="undo-2" />{t('exec.undo_all')}</Button>
      </div>
    {/if}
  </SidePanel>
</div>
