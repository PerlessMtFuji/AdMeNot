<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import { categoryKey } from '../lib/categories';
  import { initial, topReasons } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import AppIcon from './AppIcon.svelte';
  import SymptomList from './SymptomList.svelte';

  type Props = { app: AppView; level: Level | null; done?: Level | null; flash?: boolean; onlevel: (level: Level) => void;
    ontoggle: () => void; onundo?: () => void; busy?: boolean };
  let { app, level, done = null, flash = false, onlevel, ontoggle, onundo, busy = false }: Props = $props();
  const gone = $derived(done === 'remove'); // usunięta w tym zleceniu: nie ma czego wybierać
  const STRIPE = { malicious: 'bad', suspicious: 'warn', review: 'neutral', safe: null } as const;
  const AVATAR = { malicious: 'bg-bad text-bad', suspicious: 'bg-warn-strong text-warn-strong', review: 'bg-soft text-soft', safe: 'bg-ok text-ok' };
  const options = $derived([
    { value: 'silence' as Level, label: t('choice.silence'), tone: 'accent' as const },
    { value: 'disable' as Level, label: t('choice.disable'), tone: 'warn' as const },
    { value: 'remove' as Level, label: t('choice.remove'), tone: 'bad' as const },
  ]);
  let open = $state(false);
  const reasons = $derived(topReasons(app, 2, (c) => t(categoryKey(c))));
</script>

<Card stripe={STRIPE[app.verdict]} class={flash ? 'flash' : ''} role="article" label={app.name}>
  <div class="flex items-center gap-3.5 py-3 pr-5 pl-6">
    <input type="checkbox" class="h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={level !== null}
      disabled={gone} aria-label={app.name} onchange={ontoggle} />
    <AppIcon icon={app.icon} class="h-11 w-11">
      <span class="grid h-11 w-11 flex-none place-items-center rounded-[13px] shadow-[inset_0_1px_0_rgb(255_255_255/.3),0_6px_14px_-6px_currentColor] {AVATAR[app.verdict]}"
        aria-hidden="true"><span class="text-lg font-extrabold text-white">{initial(app.name)}</span></span>
    </AppIcon>
    <div class="min-w-0 flex-1">
      <div class="flex min-w-0 items-center gap-2">
        <b class="truncate text-md" title={app.package}>{app.name}</b>
        {#if app.incomplete}<Pill tone="neutral">{t('results.incomplete')}</Pill>{/if}
        {#if done}<Pill tone="ok">{t(`history.level_done.${done}`)}</Pill>
          {#if onundo}<Button variant="ghost" size="sm" disabled={busy} label={t('summary.undo_app', { name: app.name })}
            onclick={onundo}><Icon name="undo-2" size={14} />{t('history.undo_changes')}</Button>{/if}{/if}
      </div>
      <div data-testid="reasons" class="truncate text-xs text-mut">
        {reasons.items.map((r) => r.label).join(' · ')}{#if reasons.more.length}<span class="text-soft"> · +{reasons.more.length}</span>{/if}
      </div>
      {#if app.symptoms.length}
        <button type="button" class="mt-0.5 text-xs font-semibold text-accent hover:underline" aria-expanded={open}
          onclick={() => (open = !open)}>{t('results.why')}</button>
      {/if}
    </div>
    <div class="w-[240px] flex-none">
      <Segmented stretch size="sm" label={t('results.action_for', { name: app.name })} value={level} {options} disabled={gone} onchange={onlevel} />
    </div>
  </div>
  {#if open}
    <div class="mono mb-1 ml-[92px] text-2xs text-soft">{app.package}</div>
    <SymptomList symptoms={app.symptoms} />
  {/if}
</Card>
