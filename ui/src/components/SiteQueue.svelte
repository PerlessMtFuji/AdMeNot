<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { siteState, type SiteState } from '../lib/logic';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import BrowserIcon from './BrowserIcon.svelte';
  import ToggleScreenMini from './ToggleScreenMini.svelte';

  // Kolejka witryn w cofaniu (wariant B makiety): wszystkie pozycje od początku, bieżąca rozwinięta.
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  /** Więcej zrobionych niż tyle — zwijają się do jednej linii. */
  const COLLAPSE_AFTER = 3;
  let now = $state(Date.now());
  $effect(() => {
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });
  const left = $derived(s.userWait ? Math.max(0, Math.round(s.userWait.timeout - (now - s.userWait.since) / 1000)) : 0);
  const time = $derived(`${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`);
  const items = $derived((s.undoSites ?? []).map((site) => ({ site, state: siteState(site, s.undoSteps, s.userWait) })));
  const done = $derived(items.filter((i) => i.state === 'done').length);
  const collapsed = $derived(done > COLLAPSE_AFTER);
  const visible = $derived(collapsed ? items.filter((i) => i.state !== 'done') : items);

  const DOT: Record<SiteState, string> = {
    done: 'bg-ok-soft text-ok', current: 'bg-accent text-white', waiting: 'border-2 border-line',
    skipped: 'border-2 border-line', gone: 'bg-warn-soft text-warn',
  };
  const TEXT: Record<SiteState, string> = { done: '', current: 'font-bold', waiting: 'text-mut', skipped: 'text-soft', gone: 'text-warn' };
  const MARK: Record<SiteState, string> = { done: '✓', current: '●', waiting: '', skipped: '', gone: '!' };
</script>

<section aria-label={t('undo.sites_title')} class="border-t border-line/70 px-4 pt-3 pb-1">
  <b class="text-lg">{t('undo.sites_title')}</b>
  <p class="text-sm text-mut">{t('undo.sites_sub')}</p>
  <ul class="mt-2.5">
    {#if collapsed}
      <li class="flex items-center gap-2.5 border-t border-line/70 py-2 text-sm font-semibold text-ok">{tp('undo.done_collapsed', done)}</li>
    {/if}
    {#each visible as { site, state } (site.action_id)}
      {@const current = state === 'current'}
      <li aria-current={current ? 'step' : undefined}
        class="flex flex-wrap items-center gap-2.5 border-t border-line/70 py-2 {current ? '-mx-4 bg-accent-soft px-4 py-2.5' : ''}">
        <span class="grid h-[18px] w-[18px] flex-none place-items-center rounded-full text-2xs {DOT[state]}" aria-hidden="true">{MARK[state]}</span>
        <BrowserIcon pkg={site.package} name={site.browser} size="sm" />
        <span class="min-w-0 truncate {TEXT[state]}">{site.browser} · {site.site ?? t('undo.site_all')}</span>
        {#if current}
          <span class="mono ml-auto text-xs text-soft">{time}</span>
          <div class="flex w-full items-center gap-3.5 pt-2 pl-7">
            <ToggleScreenMini tone="on" compact label={site.site ?? site.browser} />
            <div class="flex min-w-0 flex-col gap-2">
              <span class="text-sm text-mut">{t('undo.site_hint')}</span>
              <div class="flex flex-wrap gap-2">
                <Button size="sm" onclick={() => ctl.reopenScreen()}><Icon name="rotate-ccw" />{t('user.reopen')}</Button>
                <Button size="sm" onclick={() => ctl.skipSite()}>{t('undo.skip')}</Button>
                {#if s.device && s.mirror.available && !ctl.mirrorActive(s.device.serial)}
                  {@const device = s.device}
                  <Button size="sm" onclick={() => ctl.mirrorStart(device.serial, device.name)}>
                    <Icon name="screen-share" />{t('mirror.show_phone')}</Button>
                {/if}
              </div>
            </div>
          </div>
        {:else}
          <span class="ml-auto flex-none text-sm {state === 'gone' ? 'text-warn' : 'text-soft'}">{t(`undo.state.${state}`)}</span>
        {/if}
      </li>
    {/each}
  </ul>
</section>
