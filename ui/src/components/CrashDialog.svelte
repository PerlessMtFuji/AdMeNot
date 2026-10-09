<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { CRASH_ERROR_KEYS, t } from '../lib/i18n/index.svelte';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const known: readonly string[] = CRASH_ERROR_KEYS;
  const errorKey = $derived(s.crashError && known.includes(s.crashError.key) ? s.crashError.key : 'internal');
  const error = $derived((s.crashPreview?.error ?? {}) as { type?: string });
  const created = $derived(String(s.crashPreview?.created ?? '').replace('T', ' '));
  let timer: ReturnType<typeof setTimeout> | undefined;

  // Podgląd = treść wysyłki; odświeżany po zmianie pola ADB lub opisu (spec raportów §5.2).
  function refresh(): void {
    clearTimeout(timer);
    timer = setTimeout(() => void ctl.previewCrash(), 300);
  }

  // Po zamknięciu okna nie może przyjść spóźniony podgląd.
  onDestroy(() => clearTimeout(timer));
</script>

{#if s.crashDialog}
  <Dialog title={t('crash.title')} oncancel={() => ctl.closeCrash()}>
    {#if s.crashSent}
      <p class="flex items-center gap-2">{t('crash.sent', { id: s.crashSent })}
        <Button size="sm" variant="ghost" onclick={() => navigator.clipboard?.writeText(s.crashSent ?? '')}>{t('crash.copy')}</Button></p>
      <p class="mt-2 text-xs text-mut">{t('crash.contact')}</p>
    {:else}
      <p>{t('crash.intro')}</p>
      {#if error.type}<p class="mt-1 text-sm text-mut">{t('crash.summary', { type: error.type, created })}</p>{/if}
      <p class="mt-1 text-xs text-mut">{t('crash.includes')}</p>
      <label class="mt-3 flex flex-col gap-1">
        <span class="text-sm">{t('crash.comment')}</span>
        <textarea class="min-h-[72px] rounded-lg border border-line bg-surface-2 p-2 text-sm" maxlength="1000"
          bind:value={s.crashComment} oninput={refresh}></textarea>
      </label>
      <label class="mt-3 flex items-start gap-2 text-sm">
        <input type="checkbox" class="mt-0.5" bind:checked={s.crashAdb} disabled={!s.crashHasAdb} onchange={refresh} />
        <span>{t('crash.adb')}</span>
      </label>
      <details class="mt-3">
        <summary class="cursor-pointer text-sm">{t('crash.show')}</summary>
        <pre class="mono mt-2 max-h-[30vh] overflow-auto rounded-lg bg-surface-2 p-2.5 text-xs whitespace-pre-wrap">{s.crashPreview ? JSON.stringify(s.crashPreview, null, 2) : ''}</pre>
      </details>
      <p class="mt-3 text-xs text-mut">{t('crash.contact')}</p>
      {#if s.crashError}
        <p role="alert" class="mt-3 text-bad">{t(`crash.error.${errorKey}`, { message: s.crashError.message })}</p>
      {/if}
    {/if}
    {#snippet actions()}
      {#if s.crashSent}
        <Button variant="primary" onclick={() => ctl.closeCrash()}>{t('common.close')}</Button>
      {:else}
        <Button variant="ghost" size="sm" disabled={s.crashSending} onclick={() => ctl.discardCrash()}>{t('crash.discard')}</Button>
        <Button disabled={s.crashSending} onclick={() => ctl.closeCrash()}>{t('crash.later')}</Button>
        <Button variant="primary" disabled={s.crashSending} onclick={() => ctl.sendCrash()}>
          {s.crashSending ? t('crash.sending') : t('crash.submit')}</Button>
      {/if}
    {/snippet}
  </Dialog>
{/if}
