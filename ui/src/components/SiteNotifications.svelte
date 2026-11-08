<script lang="ts">
  import { getContext } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { initial, phoneBadge, siteRows } from '../lib/logic';
  import type { CheckBrowser, CheckSite, DeviceCheck } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import BrowserIcon from './BrowserIcon.svelte';

  let { check }: { check: DeviceCheck } = $props();
  // Wcięcie rozwiniętych objaśnień pod wierszem — równo z tekstem po ikonie (jedno miejsce przy zmianie rozmiaru ikony).
  const INDENT = 'pl-10';
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');

  // Lista po witrynach tam, gdzie przeglądarka pokazuje każdą witrynę osobno: jeden wiersz = jedna rzecz do
  // zrobienia, z powiadomieniem na ekranie na górze (to je klient widzi i ich zwykle dotyczy skarga). Przeglądarka
  // ze wspólnym kanałem (Samsung Internet, Firefox bez debugowania) to jeden wiersz: jej witryny z ekranu,
  // „Wycisz wszystkie” i podpowiedź — zamiast trzech osobnych wierszy tej samej przeglądarki.
  const rows = $derived(siteRows(check));
  const { todo, done, shared: sharedRows, unsupported, unreadable, rdpOff } = $derived(rows);
  const allFix = $derived(check.browsers.filter((b) => b.all_fix));
  const onScreen = (b: CheckBrowser) => b.sites.filter((x) => x.active && !x.blocked);
  const picked = $derived([...todo.map((r) => r.site.fix), ...allFix.map((b) => b.all_fix)].filter((f) => f && s.fixes.has(f)).length);
  const ok = $derived(check.state === 'ok');
  // Brak wierszy do pokazania (stopka może mieć jeszcze „już wyłączone”): zdanie zamiast pustej listy.
  const empty = $derived(!todo.length && !sharedRows.length && !unsupported.length);

  // Liczba w pigułce nagłówka to ta sama jednostka co licznik zakładki „Telefon”: wiersze do zrobienia tej kontroli.
  const badge = $derived(phoneBadge([check]));
  const toCheck = $derived(badge.kind === 'count' ? badge.count : 0);

  // Długie instrukcje w wierszach chowają się pod przyciskiem: „jak sprawdzić” (przeglądarka, której powiadomień
  // nie umiemy odczytać) albo „szczegóły” (reszta). Stan per wiersz: pakiet (wiersz przeglądarki) albo pakiet + origin
  // (wiersz witryny).
  const howOpen = new SvelteSet<string>();
  const toggleHow = (key: string) => (howOpen.has(key) ? howOpen.delete(key) : howOpen.add(key));
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

<!-- Przycisk rozwijający instrukcję wiersza; nazwa dostępna zawiera nazwę przeglądarki albo hosta. -->
{#snippet more(key: string, name: string, label: string)}
  {@const open = howOpen.has(key)}
  <button type="button" class="flex-none text-sm font-semibold text-accent hover:underline" aria-expanded={open}
    aria-label="{open ? t('checks.howto_hide') : label}: {name}" onclick={() => toggleHow(key)}>{open ? t('checks.howto_hide') : label}</button>
{/snippet}

<div class="card rounded-2xl p-4">
  <div class="flex items-start gap-3">
    {#if ok}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-ok-soft text-ok"><Icon name="check" size={14} strokeWidth={3} /></span>
    {:else}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-warn-soft text-warn"><Icon name="bell-ring" size={14} /></span>
    {/if}
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="font-bold">{t(`checks.${check.id}`)}</h2>
        {#if toCheck}<Pill tone="warn">{tp('checks.to_check', toCheck)}</Pill>{:else}<Pill tone={ok ? 'ok' : 'warn'}>{check.state_label}</Pill>{/if}
        {#if picked}<Pill tone="accent">{tp('checks.picked', picked)}</Pill>{/if}
      </div>
      <span class="text-sm text-mut">{t('checks.intro')}</span>
    </div>
  </div>

  {#if empty}
    {#if ok || !done.length}<p class="mt-3 border-t border-line pt-2.5 text-sm text-mut">{ok ? t('checks.ok_sub') : t('checks.none')}</p>{/if}
  {:else}
    <ul class="mt-3 flex flex-col border-t border-line">
      {#each todo as { site, browser } (browser.package + site.origin)}
        {@const key = browser.package + site.origin}
        {@const hint = site.active && !site.fix && browser.block_action}
        <li class="border-b border-line py-2.5">
          <div class="flex items-center gap-3">
            <span class="grid h-7 w-7 flex-none place-items-center rounded-lg bg-accent-soft text-sm font-extrabold text-accent" aria-hidden="true">{initial(site.host)}</span>
            <span class="flex min-w-0 flex-1 flex-col">
              <b class="truncate" title={detail(site)}>{site.host}</b>
              <span class="flex items-center gap-1.5 text-xs text-soft"><BrowserIcon pkg={browser.package} name={browser.name} size="sm" />{browser.name}</span>
            </span>
            {#if site.active}<Pill tone="bad">{t('checks.active')}</Pill>{:else}<Pill tone="warn">{t('checks.can_send')}</Pill>{/if}
            {#if hint}{@render more(key, site.host, t('checks.details'))}{/if}
            {#if site.fix}{@render toggle(site.fix, t('checks.silence_site', { host: site.host }), site.fix_label)}{/if}
          </div>
          {#if hint && howOpen.has(key)}<p class="mt-1.5 {INDENT} text-sm text-soft">{t('checks.active_no_fix')}</p>{/if}
        </li>
      {/each}
      {#each sharedRows as b (b.package)}
        {@const live = onScreen(b)}
        {@const open = howOpen.has(b.package)}
        <li class="border-b border-line py-2.5">
          <div class="flex items-center gap-3">
            <BrowserIcon pkg={b.package} name={b.name} />
            <span class="flex min-w-0 flex-1 flex-col gap-0.5">
              <b class="truncate">{b.name}</b>
              {#if live.length}
                <span class="flex flex-wrap items-center gap-x-1.5 text-sm text-bad">{t('checks.on_screen')}
                  {#each live as site, i (site.origin)}<b class="font-semibold" title={detail(site)}>{site.host}</b>{i < live.length - 1 ? ',' : ''}{/each}
                </span>
              {/if}
              {#if b.rdp_hint}<span class="text-sm text-soft">{t('checks.rdp_short')}</span>{/if}
            </span>
            {#if b.rdp_hint}<span class="spin flex-none" aria-hidden="true"></span>{/if}
            {@render more(b.package, b.name, t('checks.details'))}
            {#if b.all_fix}{@render toggle(b.all_fix, t('checks.all', { browser: b.name }), b.all_fix_label, t('checks.silence_all'))}{/if}
          </div>
          {#if open}
            <div class="mt-1.5 flex flex-col gap-1 {INDENT} text-sm text-soft">
              <span>{b.rdp_hint ? t('checks.rdp') : t('checks.all_sub')}</span>
              {#if live.length && b.block_action}<span>{t('checks.active_no_fix')}</span>{/if}
            </div>
          {/if}
        </li>
      {/each}
      {#each unsupported as b (b.package)}
        {@const how = howOpen.has(b.package)}
        <li class="border-b border-line py-2.5">
          <div class="flex items-center gap-3">
            <BrowserIcon pkg={b.package} name={b.name} />
            <span class="flex min-w-0 flex-1 flex-col">
              <b class="truncate" title={expert ? b.package : undefined}>{b.name}</b>
            </span>
            <Pill tone="neutral">{t('checks.unsupported_pill')}</Pill>
            {@render more(b.package, b.name, t('checks.howto'))}
          </div>
          {#if how}<p class="mt-1.5 {INDENT} text-sm text-soft">{t('checks.unsupported', { browser: b.name })}</p>{/if}
        </li>
      {/each}
    </ul>
  {/if}
  {#if done.length || unreadable.length || rdpOff.length}
    <div class="flex flex-wrap items-center gap-x-5 gap-y-1.5 pt-2.5 text-sm text-soft {empty && !(ok || !done.length) ? 'mt-3 border-t border-line' : ''}">
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
