<script lang="ts">
  import { getContext } from 'svelte';
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { evidenceGroups, initial, planEntries, VERDICT_TONE } from '../lib/logic';
  import type { AppView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import ScoreScale from './ScoreScale.svelte';

  let { app }: { app: AppView | null } = $props();
  const ctl = getContext<Controller | undefined>('ctl');
  const groups = $derived(app ? evidenceGroups(app.findings) : { groups: [], combos: [] });
  const count = $derived(ctl ? planEntries(ctl.state.scan?.apps ?? [], ctl.state.selection).length : 0);
  const AVATAR = { malicious: 'bg-bad', suspicious: 'bg-warn-strong', review: 'bg-soft', safe: 'bg-ok' };
</script>

{#if app}
  <div class="flex items-center gap-2.5">
    <span class="grid h-9 w-9 flex-none place-items-center rounded-[10px] text-[15px] font-extrabold text-white {AVATAR[app.verdict]}" aria-hidden="true">{initial(app.name)}</span>
    <div class="min-w-0 flex-1"><b class="block truncate text-[14px]">{app.name}</b>{#if app.name !== app.package}<span class="mono block truncate text-[10px] text-soft">{app.package}</span>{/if}</div>
    <Pill tone={VERDICT_TONE[app.verdict]}>{app.verdict_label}</Pill>
  </div>
  <div><span class="lbl">{t('evidence.score')}</span><ScoreScale score={app.score} verdict={app.verdict} /></div>
  <span class="lbl">{t('evidence.why')}</span>
  <div class="flex flex-col gap-2">
    {#each groups.groups as g (g.category)}
      <div>
        <div class="flex items-center gap-2 font-bold"><span class="text-mut"><Icon name={CATEGORY_ICON[g.category]} /></span>{t(categoryKey(g.category))}</div>
        {#each g.items as f (f.rule_id)}
          <div class="flex gap-2 py-0.5 pl-[22px] text-ink"><span class="min-w-0 flex-1">{f.label}</span><span class="text-[11px] text-soft tabular-nums">+{f.weight}</span></div>
        {/each}
      </div>
    {/each}
    {#each groups.combos as c (c.rule_id)}
      <div class="flex gap-2 border-t border-dashed border-line pt-1.5 text-[11px] text-mut"><span class="flex-1">{c.label}</span><span class="text-soft tabular-nums">+{c.weight}</span></div>
    {/each}
    {#if app.apk_error}
      <div class="flex items-center gap-2 text-[11px] text-mut"><Icon name="triangle-alert" />{t('expert.apk_error')}: {app.apk_error}</div>
    {/if}
  </div>
  <details class="text-[11px]">
    <summary class="cursor-pointer font-semibold text-accent">{t('evidence.raw')}</summary>
    <pre class="mono mt-1.5 rounded-lg bg-surface-2 p-2 text-[10.5px] whitespace-pre-wrap text-mut">{app.findings.filter((f) => f.category !== 'combo').map((f) => f.text_expert).join('\n')}{app.ad_sdks?.length ? `\n${t('expert.ad_sdks', { list: app.ad_sdks.join(', ') })}` : ''}</pre>
  </details>
{:else}
  <p class="text-mut">{t('evidence.none')}</p>
{/if}
{#if ctl}
  <div class="mt-auto flex items-center gap-2.5 border-t border-line pt-3">
    <div class="min-w-0 flex-1"><span class="lbl block">{t('evidence.plan')}</span><b>{tp('panel.apps', count)}</b></div>
    <Button variant="primary" disabled={count === 0 || ctl.state.orderRunning} onclick={() => ctl.openPlan()}>{t('evidence.fix', { count })}</Button>
  </div>
{/if}
