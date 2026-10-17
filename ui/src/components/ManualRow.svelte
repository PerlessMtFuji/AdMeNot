<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { factTags, initial } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import AppCard from './AppCard.svelte';
  import AppIcon from './AppIcon.svelte';

  // Wiersz trybu ręcznego: bez werdyktu i objawów (heurystyki są ukryte), tylko fakty z telefonu.
  // Po analizie na żądanie — zwykła karta aplikacji z werdyktem.
  let { app }: { app: AppView } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const analyzed = $derived(s.scan?.on_demand.includes(app.package) ?? false);
  const level = $derived(s.selection[app.package] ?? null);
  const done = $derived(s.acted[app.package] ?? null);
  const tags = $derived(factTags(app));
  const date = $derived(app.first_install
    ? new Date(app.first_install).toLocaleDateString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB') : null);
  const options = $derived([
    { value: 'silence' as Level, label: t('choice.silence'), tone: 'accent' as const },
    { value: 'disable' as Level, label: t('choice.disable'), tone: 'warn' as const },
    { value: 'remove' as Level, label: t('choice.remove'), tone: 'bad' as const },
  ]);
</script>

{#if analyzed}
  <AppCard {app} {level} {done} busy={s.orderRunning} flash={s.apk.changed.includes(app.package)}
    onundo={() => ctl.undoApp(app.package)} onlevel={(l) => ctl.setLevel(app.package, l)} ontoggle={() => ctl.toggle(app)} />
{:else}
  <Card role="article" label={app.name}>
    <div class="flex items-center gap-3.5 py-3 pr-5 pl-6">
      <input type="checkbox" class="h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={level !== null}
        disabled={done === 'remove'} aria-label={app.name} onchange={() => ctl.toggle(app)} />
      <AppIcon icon={app.icon} class="h-11 w-11">
        <span class="grid h-11 w-11 flex-none place-items-center rounded-[13px] bg-soft text-lg font-extrabold text-white" aria-hidden="true">{initial(app.name)}</span>
      </AppIcon>
      <div class="min-w-0 flex-1">
        <div class="flex min-w-0 items-center gap-2">
          <b class="truncate text-md" title={app.package}>{app.name}</b>
          {#if done}<Pill tone="ok">{t(`history.level_done.${done}`)}</Pill>
            <Button variant="ghost" size="sm" disabled={s.orderRunning} label={t('summary.undo_app', { name: app.name })}
              onclick={() => ctl.undoApp(app.package)}><Icon name="undo-2" size={14} />{t('history.undo_changes')}</Button>{/if}
        </div>
        <div class="mono truncate text-2xs text-soft">{app.package}{#if date} · {t('manual.installed', { date })}{/if}</div>
        {#if tags.length}
          <div class="mt-1 flex flex-wrap gap-1.5">
            {#each tags as tag (tag)}<Pill tone="neutral">{t(`manual.tag.${tag}`)}</Pill>{/each}
          </div>
        {/if}
      </div>
      <div class="w-[240px] flex-none max-[1200px]:w-[210px]">
        <Segmented stretch size="sm" label={t('results.action_for', { name: app.name })} value={level} {options}
          disabled={done === 'remove'} onchange={(l) => ctl.setLevel(app.package, l)} />
      </div>
    </div>
  </Card>
{/if}
