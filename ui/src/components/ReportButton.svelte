<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  type Props = { order: string; variant?: 'secondary' | 'ghost'; size?: 'sm' | 'md' | 'lg' };
  let { order, variant = 'secondary', size = 'md' }: Props = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const busy = $derived(s.reportBusy === order);
  const last = $derived(s.reports[order]);
</script>

<div class="flex flex-col gap-1">
  <Button {variant} {size} disabled={s.reportBusy !== null} onclick={() => ctl.report(order)}>
    <Icon name="file-text" />{busy ? t('report.busy') : t('report.button')}
  </Button>
  {#if last && !busy}
    {#if last.error}
      <span class="text-xs text-warn">{t(`report.pdf_${last.error}`, { pdf: last.html.replace(/\.html$/, '.pdf'), html: last.html })}</span>
    {:else}
      <span class="mono flex items-center gap-1 text-xs text-ok"><Icon name="check" size={13} />{t('report.opened', { path: last.pdf ?? last.html })}</span>
    {/if}
  {/if}
</div>
