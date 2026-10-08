<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, UPDATE_ERROR_KEYS } from '../lib/i18n/index.svelte';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Progress from '../ui/Progress.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const u = $derived(s.update);
  const running = $derived(s.job?.kind === 'update');
  const known: readonly string[] = UPDATE_ERROR_KEYS;
  const errorKey = $derived(s.updateError && known.includes(s.updateError.key) ? s.updateError.key : 'internal');
  const mb = (bytes: number) => (bytes / 1_048_576).toFixed(1);
  const progress = $derived(s.updateProgress);
</script>

{#if s.updateDialog && u?.available}
  <Dialog title={t('update.dialog_title', { version: u.available.version })} oncancel={() => ctl.closeUpdate()}>
    {#if u.retired}
      <p class="mb-2 font-semibold text-bad">{u.retired.reason ?? t('update.retired_title')}</p>
    {/if}
    <div class="max-h-[40vh] overflow-auto whitespace-pre-line text-ink">{u.available.notes}</div>
    <p class="mt-3">{u.installable ? t('update.confirm', { version: u.available.version }) : t('update.dev')}</p>
    {#if progress}
      <div class="mt-4 flex flex-col gap-1.5">
        <Progress value={progress.total ? progress.done / progress.total : 0} label={t('update.downloading')} />
        <span class="text-xs">{progress.total
          ? t('update.progress', { done: mb(progress.done), total: mb(progress.total) })
          : t('update.progress_unknown', { done: mb(progress.done) })}</span>
      </div>
    {/if}
    {#if s.updateError}
      <p role="alert" class="mt-3 text-bad">{t(`update.error.${errorKey}`, { page: String(s.updateError.page ?? '') })}</p>
    {/if}
    {#snippet actions()}
      {#if running}
        <Button onclick={() => ctl.cancelUpdate()}>{t('common.cancel')}</Button>
      {:else}
        <Button onclick={() => ctl.closeUpdate()}>{t('common.cancel')}</Button>
        <Button variant="primary" disabled={s.job !== null} onclick={() => ctl.installUpdate()}>
          {s.updateError ? t('update.retry') : t('update.install')}</Button>
      {/if}
    {/snippet}
  </Dialog>
{/if}
