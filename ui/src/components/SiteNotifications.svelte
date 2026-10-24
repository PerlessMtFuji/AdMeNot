<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { initial } from '../lib/logic';
  import type { CheckBrowser, CheckSite, DeviceCheck } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import BrowserIcon from './BrowserIcon.svelte';

  let { check }: { check: DeviceCheck } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');

  // Lista po witrynach tam, gdzie przeglądarka pokazuje każdą witrynę osobno: jeden wiersz = jedna rzecz do
  // zrobienia, z powiadomieniem na ekranie na górze (to je klient widzi i ich zwykle dotyczy skarga). Przeglądarka
  // ze wspólnym kanałem (Samsung Internet, Firefox bez debugowania) to jeden wiersz: jej witryny z ekranu,
  // „Wycisz wszystkie” i podpowiedź — zamiast trzech osobnych wierszy tej samej przeglądarki.
  const shared = (b: CheckBrowser) => b.mode === 'shared';
  const todo = $derived(check.browsers.filter((b) => !shared(b))
    .flatMap((browser) => browser.sites.filter((x) => !x.blocked).map((site) => ({ site, browser })))
    .sort((a, b) => Number(b.site.active) - Number(a.site.active)));
  const done = $derived(check.browsers.flatMap((browser) => browser.sites.filter((x) => x.blocked).map((site) => ({ site, browser }))));
  const allFix = $derived(check.browsers.filter((b) => b.all_fix));
  const onScreen = (b: CheckBrowser) => b.sites.filter((x) => x.active && !x.blocked);
  const sharedRows = $derived(check.browsers.filter((b) => shared(b) && (b.all_fix || b.rdp_hint || onScreen(b).length)));
  // Przeglądarka, której powiadomień nie umiemy odczytać: wiersz z instrukcją zamiast cichego pominięcia.
  const unsupported = $derived(check.browsers.filter((b) => b.read === 'unsupported'));
  const rdpOff = $derived(check.browsers.filter((b) => b.mode === 'rdp'));
  const unreadable = $derived(check.browsers.filter((b) => b.read === 'unrecognized'));
  const fixable = $derived(todo.filter((r) => r.site.fix).length + allFix.length);
  const picked = $derived([...todo.map((r) => r.site.fix), ...allFix.map((b) => b.all_fix)].filter((f) => f && s.fixes.has(f)).length);
  const ok = $derived(check.state === 'ok');

  // Zwinięta, gdy wszystko w porządku; ręczne rozwinięcie albo zwinięcie przesłania ten domyślny stan.
  let chosen = $state<boolean | null>(null);
  const open = $derived(chosen ?? !ok);
  // Origin i identyfikator poprawki tylko dla eksperta, w dymku — nie w treści wiersza.
  const detail = (site: CheckSite) => (expert ? [site.origin, site.fix].filter(Boolean).join(' · ') : undefined);
</script>

{#snippet toggle(fix: string, label: string, title: string | null, text: string = t('checks.silence'))}
  <label class="flex flex-none cursor-pointer items-center gap-2 text-sm font-semibold whitespace-nowrap text-mut">
    {text}
    <input type="checkbox" role="switch" aria-label={label} title={expert ? (title ?? fix) : undefined}
      class="switch" checked={s.fixes.has(fix)} disabled={s.orderRunning} onchange={() => ctl.toggleFix(fix)} />
  </label>
{/snippet}

<div class="card rounded-2xl {open ? 'p-4' : 'px-4 py-3'}">
  <button type="button" class="flex w-full items-start gap-3 text-left" aria-expanded={open} onclick={() => (chosen = !open)}>
    {#if ok}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-ok-soft text-ok"><Icon name="check" size={14} strokeWidth={3} /></span>
    {:else}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-warn-soft text-warn"><Icon name="bell-ring" size={14} /></span>
    {/if}
    <span class="flex min-w-0 flex-1 flex-col gap-0.5">
      <span class="flex flex-wrap items-center gap-2">
        <b>{t(`checks.${check.id}`)}</b>
        {#if fixable}<Pill tone="warn">{tp('checks.to_fix', fixable)}</Pill>{:else}<Pill tone={ok ? 'ok' : 'warn'}>{check.state_label}</Pill>{/if}
        {#if picked}<Pill tone="accent">{tp('checks.picked', picked)}</Pill>{/if}
        {#if !open}
          <span class="flex items-center gap-1">{#each check.browsers as b (b.package)}<BrowserIcon pkg={b.package} name={b.name} size="sm" />{/each}</span>
          {#if ok}<span class="text-sm text-soft">{t('checks.ok_sub')}</span>{/if}
        {/if}
      </span>
      {#if open}<span class="text-sm text-mut">{t('checks.intro')}</span>{/if}
    </span>
    <Icon name="chevron-down" size={16} class="mt-1 flex-none text-soft transition-transform duration-150 {open ? 'rotate-180' : ''}" />
  </button>

  {#if open}
    <ul class="mt-3 flex flex-col border-t border-line">
      {#each todo as { site, browser } (browser.package + site.origin)}
        <li class="flex items-center gap-3 border-b border-line py-2.5">
          <span class="grid h-7 w-7 flex-none place-items-center rounded-lg bg-accent-soft text-sm font-extrabold text-accent" aria-hidden="true">{initial(site.host)}</span>
          <span class="flex min-w-0 flex-1 flex-col">
            <b class="truncate" title={detail(site)}>{site.host}</b>
            <span class="flex items-center gap-1.5 text-xs text-soft"><BrowserIcon pkg={browser.package} name={browser.name} size="sm" />{browser.name}</span>
            {#if site.active && !site.fix && browser.block_action}<span class="text-sm text-mut">{t('checks.active_no_fix')}</span>{/if}
          </span>
          {#if site.active}<Pill tone="bad">{t('checks.active')}</Pill>{:else}<Pill tone="warn">{t('checks.can_send')}</Pill>{/if}
          {#if site.fix}{@render toggle(site.fix, t('checks.silence_site', { host: site.host }), site.fix_label)}{/if}
        </li>
      {/each}
      {#each sharedRows as b (b.package)}
        {@const live = onScreen(b)}
        <li class="flex items-center gap-3 border-b border-line py-2.5">
          <BrowserIcon pkg={b.package} name={b.name} />
          <span class="flex min-w-0 flex-1 flex-col gap-0.5">
            <b class="truncate">{b.name}</b>
            {#if live.length}
              <span class="flex flex-wrap items-center gap-x-1.5 text-sm text-bad">{t('checks.on_screen')}
                {#each live as site, i (site.origin)}<b class="font-semibold" title={detail(site)}>{site.host}</b>{i < live.length - 1 ? ',' : ''}{/each}
              </span>
            {/if}
            <span class="text-sm text-soft">{b.rdp_hint ? t('checks.rdp') : t('checks.all_sub')}</span>
            {#if live.length && b.block_action}<span class="text-sm text-soft">{t('checks.active_no_fix')}</span>{/if}
          </span>
          {#if b.rdp_hint}<span class="spin flex-none" aria-hidden="true"></span>{/if}
          {#if b.all_fix}{@render toggle(b.all_fix, t('checks.all', { browser: b.name }), b.all_fix_label, t('checks.silence_all'))}{/if}
        </li>
      {/each}
      {#each unsupported as b (b.package)}
        <li class="flex items-center gap-3 border-b border-line py-2.5">
          <BrowserIcon pkg={b.package} name={b.name} />
          <span class="flex min-w-0 flex-1 flex-col">
            <b class="truncate" title={expert ? b.package : undefined}>{b.name}</b>
            <span class="text-sm text-soft">{t('checks.unsupported', { browser: b.name })}</span>
          </span>
          <Pill tone="neutral">{t('checks.unsupported_pill')}</Pill>
        </li>
      {/each}
    </ul>

    {#if !todo.length && !sharedRows.length && !unsupported.length && !done.length}
      <p class="pt-2.5 text-sm text-mut">{t('checks.none')}</p>
    {/if}
    {#if done.length || unreadable.length || rdpOff.length}
      <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 pt-2.5 text-sm text-soft">
        {#if done.length}
          <span class="flex flex-wrap items-center gap-1.5">
            <Icon name="check" size={14} strokeWidth={3} class="text-ok" />{t('checks.done')}
            {#each done as { site, browser }, i (browser.package + site.origin)}
              <span class="flex items-center gap-1" title={detail(site)}><BrowserIcon pkg={browser.package} name={browser.name} size="sm" />{site.host}{i < done.length - 1 ? ',' : ''}</span>
            {/each}
          </span>
        {/if}
        {#if unreadable.length}
          <span class="flex items-center gap-1.5">{t('checks.unreadable')}
            {#each unreadable as b (b.package)}<BrowserIcon pkg={b.package} name={b.name} size="sm" />{b.name}{/each}</span>
        {/if}
        {#each rdpOff as b (b.package)}
          <span class="ml-auto flex items-center gap-1.5"><Icon name="triangle-alert" size={14} class="text-warn" />{t('checks.rdp_off')}</span>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  /* Przełącznik z samego pola wyboru: gałka to tło, więc pole zostaje klikalne i dostępne jak zwykły checkbox. */
  .switch {
    appearance: none; flex: none; width: 36px; height: 20px; border-radius: 999px; cursor: pointer;
    background: var(--color-line) radial-gradient(circle, var(--color-mut) 7px, transparent 7.5px) no-repeat 0 0 / 20px 20px;
    transition: background-color .15s, background-position .15s;
  }
  .switch:checked {
    background-color: var(--color-accent);
    background-image: radial-gradient(circle, #fff 7px, transparent 7.5px);
    background-position: 16px 0;
  }
  .switch:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
  .switch:disabled { opacity: .5; cursor: default; }
</style>
