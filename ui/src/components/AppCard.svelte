<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import { initial, VERDICT_TONE } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import Card from '../ui/Card.svelte';
  import Pill from '../ui/Pill.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import SymptomList from './SymptomList.svelte';

  type Props = { app: AppView; level: Level | null; flash?: boolean; onlevel: (level: Level) => void; ontoggle: () => void };
  let { app, level, flash = false, onlevel, ontoggle }: Props = $props();
  const STRIPE = { malicious: 'bad', suspicious: 'warn', review: 'neutral', safe: null } as const;
  const AVATAR = { malicious: 'bg-bad', suspicious: 'bg-warn-strong', review: 'bg-soft', safe: 'bg-ok' };
  const options = $derived([
    { value: 'silence' as Level, label: t('choice.silence'), tone: 'accent' as const },
    { value: 'disable' as Level, label: t('choice.disable'), tone: 'warn' as const },
    { value: 'remove' as Level, label: t('choice.remove'), tone: 'bad' as const },
  ]);
</script>

<Card stripe={STRIPE[app.verdict]} class={flash ? 'flash' : ''} role="article" label={app.name}>
  <div class="flex items-center gap-3 py-3 pr-4 pl-5">
    <input type="checkbox" class="h-4 w-4 flex-none accent-[var(--color-accent)]" checked={level !== null}
      aria-label={app.name} onchange={ontoggle} />
    <span class="grid h-9 w-9 flex-none place-items-center rounded-[10px] text-[15px] font-extrabold text-white {AVATAR[app.verdict]}"
      aria-hidden="true">{initial(app.name)}</span>
    <div class="min-w-0 flex-1">
      <div class="flex min-w-0 items-center gap-2">
        <b class="truncate text-[14px]">{app.name}</b>
        <Pill tone={VERDICT_TONE[app.verdict]}>{app.verdict_label}</Pill>
      </div>
      <div class="mono truncate text-[10.5px] text-soft">{app.package}</div>
    </div>
    <div class="w-[204px] flex-none">
      <Segmented stretch size="sm" label={t('results.action_for', { name: app.name })} value={level} {options} onchange={onlevel} />
    </div>
  </div>
  <SymptomList symptoms={app.symptoms} />
</Card>
