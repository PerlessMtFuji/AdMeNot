<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import { initial, VERDICT_TONE } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import Card from '../ui/Card.svelte';
  import Pill from '../ui/Pill.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import AppIcon from './AppIcon.svelte';
  import SymptomList from './SymptomList.svelte';

  type Props = { app: AppView; level: Level | null; flash?: boolean; onlevel: (level: Level) => void; ontoggle: () => void };
  let { app, level, flash = false, onlevel, ontoggle }: Props = $props();
  const STRIPE = { malicious: 'bad', suspicious: 'warn', review: 'neutral', safe: null } as const;
  const AVATAR = { malicious: 'bg-bad text-bad', suspicious: 'bg-warn-strong text-warn-strong', review: 'bg-soft text-soft', safe: 'bg-ok text-ok' };
  const options = $derived([
    { value: 'silence' as Level, label: t('choice.silence'), tone: 'accent' as const },
    { value: 'disable' as Level, label: t('choice.disable'), tone: 'warn' as const },
    { value: 'remove' as Level, label: t('choice.remove'), tone: 'bad' as const },
  ]);
</script>

<Card stripe={STRIPE[app.verdict]} class={flash ? 'flash' : ''} role="article" label={app.name}>
  <div class="flex items-center gap-3.5 py-4 pr-5 pl-6">
    <input type="checkbox" class="h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={level !== null}
      aria-label={app.name} onchange={ontoggle} />
    <AppIcon icon={app.icon} class="h-11 w-11">
      <span class="grid h-11 w-11 flex-none place-items-center rounded-[13px] shadow-[inset_0_1px_0_rgb(255_255_255/.3),0_6px_14px_-6px_currentColor] {AVATAR[app.verdict]}"
        aria-hidden="true"><span class="text-lg font-extrabold text-white">{initial(app.name)}</span></span>
    </AppIcon>
    <div class="min-w-0 flex-1">
      <div class="flex min-w-0 items-center gap-2">
        <b class="truncate text-md">{app.name}</b>
        <Pill tone={VERDICT_TONE[app.verdict]}>{app.verdict_label}</Pill>
      </div>
      <div class="mono truncate text-2xs text-soft">{app.package}</div>
    </div>
    <div class="w-[240px] flex-none">
      <Segmented stretch size="sm" label={t('results.action_for', { name: app.name })} value={level} {options} onchange={onlevel} />
    </div>
  </div>
  <SymptomList symptoms={app.symptoms} />
</Card>
