<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { type StageState, stageStates } from '../lib/logic';

  const s = getContext<Controller>('ctl').state;
  const STAGES = ['connect', 'read', 'analyze', 'fix', 'report'] as const;
  const states = $derived(stageStates(s.phase, s.scanStage));
  const cls: Record<StageState, string> = {
    done: 'border-[#86efac] bg-[#dcfce7] text-[#166534]',
    now: 'border-accent bg-accent text-white',
    todo: 'border-line bg-card text-mut',
    off: 'border-line bg-card text-mut opacity-50',
  };
</script>

<ol class="flex gap-1.5" aria-label={t('stage.label')}>
  {#each STAGES as stage, i (stage)}
    <li class="flex-1 rounded-[7px] border p-1.5 text-center text-[11px] font-semibold {cls[states[i]]}"
      aria-current={states[i] === 'now' ? 'step' : undefined}
      title={stage === 'report' ? t('stage.soon') : undefined}>
      {i + 1} {t(`stage.${stage}`)}{states[i] === 'done' ? ' ✓' : ''}
    </li>
  {/each}
</ol>
