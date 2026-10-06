<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import type { Notice, NoticeKey } from '../lib/logic';
  import Icon from '../ui/Icon.svelte';

  let { items, details = {} }: { items: Notice[]; details?: Partial<Record<NoticeKey, string[]>> } = $props();
  let open = $state(false);
  // Ton linii: ostrzeżenie, jeśli którakolwiek uwaga jest ostrzeżeniem.
  const tone = $derived(items.some((n) => n.tone === 'warn') ? 'warn' : 'info');
  const BOX = { warn: 'border-warn-strong/40 bg-warn-soft text-warn', info: 'border-line card text-mut' };
</script>

{#if items.length}
  <div role="region" aria-label={t('notice.label')} data-tone={tone} class="rounded-xl border px-3.5 py-2 text-sm {BOX[tone]}">
    <div class="flex items-center gap-2.5">
      <Icon name="info" size={16} />
      <span role="status" class="min-w-0 flex-1 truncate text-ink">{t(`notice.short.${items[0].key}`, items[0].params)}
        {#if items.length > 1}<span class="ml-1 font-semibold text-soft">+{items.length - 1}</span>{/if}</span>
      <button type="button" class="flex-none font-semibold text-accent hover:underline" aria-expanded={open}
        onclick={() => (open = !open)}>{open ? t('notice.less') : t('notice.more')}</button>
    </div>
    {#if open}
      <ul class="mt-2 flex list-disc flex-col gap-1.5 pl-9 text-ink">
        {#each items as n (n.key)}
          <li>{t(`summary.${n.key}`, n.params)}
            {#if details[n.key]?.length}
              <ul class="mt-1 list-none text-xs text-mut">{#each details[n.key]! as d (d)}<li class="mono">{d}</li>{/each}</ul>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
