<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import { SCORE_ZONES } from '../lib/logic';
  import type { Verdict } from '../lib/types';

  let { score, verdict }: { score: number; verdict: Verdict } = $props();
  const MARK = { safe: 'text-ok', review: 'text-neutral', suspicious: 'text-warn', malicious: 'text-bad' };
  const ZONE = { safe: 'bg-neutral-soft', review: 'bg-line', suspicious: 'bg-soft/40', malicious: 'bg-bad-soft' };
  const left = $derived(Math.min(98, Math.max(2, score)));
</script>

<div role="meter" aria-label={t('evidence.score')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={score}>
  <div class="relative mt-5 flex h-2 overflow-visible rounded">
    {#each SCORE_ZONES as z (z.verdict)}<span class="flex-1 first:rounded-l last:rounded-r {ZONE[z.verdict]}"></span>{/each}
    <span class="absolute -top-[21px] -translate-x-1/2 text-xs font-extrabold {MARK[verdict]}" style="left: {left}%">
      {score}<i class="absolute top-[15px] left-1/2 block h-3.5 w-0.5 -translate-x-1/2 rounded bg-current"></i>
    </span>
  </div>
  <div class="mt-1.5 flex text-2xs text-soft">
    {#each SCORE_ZONES as z (z.verdict)}<span class="flex-1 text-center">{t(`evidence.zone.${z.verdict}`)}</span>{/each}
  </div>
</div>
