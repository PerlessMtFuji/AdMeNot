<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  // `label` + `hint`: główny przycisk w dwóch liniach („Protokół” / „PDF do podpisu”), bez ikony.
  // `compact` (wąska kolumna, np. wiersz Historii): w potwierdzeniu sama nazwa pliku, pełna ścieżka w podpowiedzi.
  type Props = { order: string; variant?: 'primary' | 'secondary' | 'ghost'; size?: 'sm' | 'md' | 'lg'; label?: string; hint?: string; compact?: boolean };
  let { order, variant = 'secondary', size = 'md', label, hint, compact = false }: Props = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const busy = $derived(s.reportBusy === order);
  const last = $derived(s.reports[order]);
  const file = $derived(last ? (last.pdf ?? last.html) : '');
  const shown = $derived(compact ? file.replace(/^.*[\\/]/, '') : file);
</script>

<!-- `min-w-0 max-w-full` + zawijanie w dowolnym miejscu: długa ścieżka nie wychodzi poza kolumnę przycisku. -->
<div class="flex min-w-0 max-w-full flex-col gap-1">
  <Button {variant} {size} class={hint ? 'flex-col !gap-0' : ''} disabled={s.reportBusy !== null} onclick={() => ctl.report(order)}>
    {#if hint}
      {busy ? t('report.busy') : (label ?? t('report.button'))}
      <small class="text-xs font-semibold opacity-85">{hint}</small>
    {:else}
      <Icon name="file-text" />{busy ? t('report.busy') : (label ?? t('report.button'))}
    {/if}
  </Button>
  {#if last && !busy}
    <!-- Błąd PDF najpierw (powód protokołu HTML); otwieranie wyłączone w ustawieniach to nie błąd. -->
    {#if last.error}
      <span class="text-xs text-warn [overflow-wrap:anywhere]">{t(`report.pdf_${last.error}`, { pdf: last.pdf_target ?? last.html.replace(/\.html$/, '.pdf'),
        dir: (last.pdf_target ?? '').replace(/[\\/][^\\/]*$/, ''), html: last.html })}</span>
    {:else if last.open_skipped}
      <span class="mono text-xs text-soft [overflow-wrap:anywhere]" title={file}>{t('report.saved', { path: shown })}</span>
    {:else if last.opened === null}
      <span class="text-xs text-warn [overflow-wrap:anywhere]" title={file}>{t('report.not_opened', { path: shown })}</span>
    {:else}
      <span class="mono flex items-start gap-1 text-xs text-ok" title={file}><Icon name="check" size={13} class="mt-0.5" /><span class="min-w-0 [overflow-wrap:anywhere]">{t('report.opened', { path: shown })}</span></span>
    {/if}
  {/if}
</div>
