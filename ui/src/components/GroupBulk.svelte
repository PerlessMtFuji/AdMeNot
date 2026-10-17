<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { bulkNeedsConfirm, groupCheck, LEVEL_TONE } from '../lib/logic';
  import type { AppView, Level, Verdict } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Pill from '../ui/Pill.svelte';

  // Zaznaczanie całej grupy werdyktu i jedna akcja dla zaznaczonych. „Wyłącz” i „Usuń” wymagają
  // potwierdzenia: serwisant ma sprawdzić, że każdą z tych aplikacji wolno zmienić.
  let { verdict, apps }: { verdict: Verdict; apps: AppView[] } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const group = $derived(t(`groups.${verdict}`));
  const check = $derived(groupCheck(apps, s.selection, s.acted));
  const actionable = $derived(apps.some((a) => s.acted[a.package] !== 'remove'));
  let box: HTMLInputElement;
  let pending = $state<{ levels: Record<string, Level>; level: Level | null } | null>(null);
  let action = $state('');

  $effect(() => {
    box.indeterminate = check === 'some';
  });

  const names = $derived(pending ? apps.filter((a) => pending!.levels[a.package]) : []);
  const systemCount = $derived(names.filter((a) => a.is_system).length);

  function ask(levels: Record<string, Level>, level: Level | null) {
    if (Object.keys(levels).length === 0) return;
    if (bulkNeedsConfirm(levels)) pending = { levels, level };
    else ctl.setLevels(levels);
  }

  function toggleAll(e: Event) {
    e.preventDefault(); // stan pola wynika z wyboru, nie z kliknięcia
    if (check === 'all') {
      ctl.setLevels(Object.fromEntries(apps.map((a) => [a.package, null])));
      return;
    }
    // potwierdzamy tylko nowe zmiany: aplikacje już zaznaczone zachowują swój wybór
    const levels = ctl.groupSelectLevels(apps);
    ask(Object.fromEntries(Object.entries(levels).filter(([p, l]) => s.selection[p] !== l)), null);
  }

  function pick(e: Event) {
    const level = (e.currentTarget as HTMLSelectElement).value as Level;
    action = '';
    (e.currentTarget as HTMLSelectElement).value = '';
    if (level) ask(ctl.groupActionLevels(apps, level), level);
  }

  function confirm() {
    if (pending) ctl.setLevels(pending.levels);
    pending = null;
  }
</script>

<div class="flex items-center gap-3 font-semibold tracking-normal normal-case">
  <label class="flex cursor-pointer items-center gap-2 hover:text-ink">
    <input type="checkbox" bind:this={box} class="h-4 w-4 accent-[var(--color-accent)]" checked={check === 'all'}
      disabled={!actionable || s.orderRunning} aria-label={t('bulk.select_all_in', { group })} onclick={toggleAll} />
    {t('bulk.select_all')}
  </label>
  <select aria-label={t('bulk.action_in', { group })} value={action} disabled={check === 'none' || s.orderRunning} onchange={pick}
    class="field -my-1 rounded-[10px] px-2 py-1 text-xs font-bold text-mut disabled:opacity-50">
    <option value="">{t('bulk.action')}</option>
    <option value="silence">{t('choice.silence')}</option>
    <option value="disable">{t('choice.disable')}</option>
    <option value="remove">{t('choice.remove')}</option>
  </select>
</div>

{#if pending}
  <Dialog title={pending.level ? tp('bulk.level_title', names.length, { level: t(`choice.${pending.level}`) })
    : tp('bulk.select_title', names.length)} oncancel={() => (pending = null)}>
    <p>{t('bulk.check')}</p>
    {#if systemCount}<p class="mt-2">{t('bulk.system', { count: systemCount })}
      {#if pending.level === 'remove'}{t('bulk.system_no_remove')}{/if}</p>{/if}
    {#if Object.values(pending.levels).includes('remove')}<p class="mt-2 font-semibold text-bad">{t('bulk.data_lost')}</p>{/if}
    <ul class="mt-3 flex flex-col gap-1 text-sm">
      {#each names as a (a.package)}
        {@const level = pending.levels[a.package]}
        <li class="flex items-center justify-between gap-3">
          <span class="min-w-0 truncate text-ink" title={a.package}>{a.name}</span>
          <Pill tone={LEVEL_TONE[level]}>{t(`choice.${level}`)}</Pill>
        </li>
      {/each}
    </ul>
    {#snippet actions()}
      <Button onclick={() => (pending = null)}>{t('common.cancel')}</Button>
      <Button variant={pending?.level === 'remove' ? 'danger' : 'primary'} onclick={confirm}>
        {pending?.level ? t('bulk.apply') : t('bulk.confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}
