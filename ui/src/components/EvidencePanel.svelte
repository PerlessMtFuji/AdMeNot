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
  import AppIcon from './AppIcon.svelte';
  import ScoreScale from './ScoreScale.svelte';

  let { app }: { app: AppView | null } = $props();
  const ctl = getContext<Controller | undefined>('ctl');
  const groups = $derived(app ? evidenceGroups(app.findings) : { groups: [], combos: [] });
  const count = $derived(ctl ? planEntries(ctl.state.scan?.apps ?? [], ctl.state.selection).length : 0);
  // Surowe dane: jeden wpis na regułę. Lista SDK tylko wtedy, gdy nie wypisała jej już reguła DM-ADSDK.
  const raw = $derived.by(() => {
    if (!app) return [];
    const rows = app.findings.filter((f) => f.category !== 'combo')
      .map((f) => ({ key: f.rule_id, label: f.label, text: f.text_expert }));
    if (app.ad_sdks?.length && !app.findings.some((f) => f.rule_id.startsWith('DM-ADSDK')))
      rows.push({ key: 'ad_sdks', label: t('evidence.ad_sdks'), text: app.ad_sdks.join(', ') });
    return rows;
  });
  const AVATAR = { malicious: 'bg-bad text-bad', suspicious: 'bg-warn-strong text-warn-strong', review: 'bg-soft text-soft', safe: 'bg-ok text-ok' };
</script>

{#if app}
  <div class="flex items-center gap-2.5">
    <AppIcon icon={app.icon} class="h-11 w-11">
      <span class="grid h-11 w-11 flex-none place-items-center rounded-[13px] shadow-[inset_0_1px_0_rgb(255_255_255/.3),0_6px_14px_-6px_currentColor] {AVATAR[app.verdict]}" aria-hidden="true"><span class="text-lg font-extrabold text-white">{initial(app.name)}</span></span>
    </AppIcon>
    <div class="min-w-0 flex-1"><b class="block truncate text-lg">{app.name}</b>{#if app.name !== app.package}<span class="mono block truncate text-2xs text-soft">{app.package}</span>{/if}</div>
    <Pill tone={VERDICT_TONE[app.verdict]}>{app.verdict_label}</Pill>
  </div>
  <div><span class="lbl">{t('evidence.score')}</span><ScoreScale score={app.score} verdict={app.verdict} /></div>
  <span class="lbl">{t('evidence.why')}</span>
  <div class="well well-list flex flex-col p-3.5 [&>*+*]:mt-2.5 [&>*+*]:pt-2.5">
    {#each groups.groups as g (g.category)}
      <div>
        <div class="flex items-center gap-2 font-bold"><span class="text-mut"><Icon name={CATEGORY_ICON[g.category]} /></span>{t(categoryKey(g.category))}</div>
        {#each g.items as f (f.rule_id)}
          <div class="flex gap-2 py-0.5 pl-[26px] text-ink"><span class="min-w-0 flex-1">{f.label}</span><span class="text-xs text-soft tabular-nums">+{f.weight}</span></div>
        {/each}
      </div>
    {/each}
    {#each groups.combos as c (c.rule_id)}
      <div class="flex gap-2 border-t border-dashed border-line pt-1.5 text-xs text-mut"><span class="flex-1">{c.label}</span><span class="text-soft tabular-nums">+{c.weight}</span></div>
    {/each}
    {#if app.apk_error}
      <div class="flex items-center gap-2 text-xs text-mut"><Icon name="triangle-alert" />{t('expert.apk_error')}: {app.apk_error}</div>
    {/if}
  </div>
  <details class="group text-xs">
    <summary class="flex cursor-pointer list-none items-center gap-1.5 font-semibold text-accent">
      <Icon name="chevron-right" size={14} class="transition-transform duration-150 group-open:rotate-90" />{t('evidence.raw')}
    </summary>
    <ul aria-label={t('evidence.raw')} class="well well-list mt-2 flex flex-col">
      {#each raw as r (r.key)}
        <li class="px-3 py-2">
          <span class="block text-xs font-bold text-ink">{r.label}</span>
          <span class="mono mt-0.5 block text-2xs break-words whitespace-pre-wrap text-mut">{r.text}</span>
        </li>
      {/each}
    </ul>
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
