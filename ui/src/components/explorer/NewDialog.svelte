<script lang="ts">
  import { untrack } from 'svelte';
  import { ERROR_KEYS, t } from '../../lib/i18n/index.svelte';
  import type { ApiErrorBody } from '../../lib/types';
  import Button from '../../ui/Button.svelte';
  import Dialog from '../../ui/Dialog.svelte';

  /** Nowy folder albo plik tekstowy w bieżącym folderze telefonu. `onsubmit` zwraca błąd do pokazania w oknie. */
  type Props = { kind: 'folder' | 'text'; where: string; onsubmit: (name: string, text: string) => Promise<ApiErrorBody | null>;
    oncancel: () => void };
  let { kind, where, onsubmit, oncancel }: Props = $props();
  const known: readonly string[] = ERROR_KEYS;
  let name = $state(untrack(() => t(kind === 'folder' ? 'explorer.new_dialog.folder_default' : 'explorer.new_dialog.text_default')));
  let text = $state('');
  let error = $state<ApiErrorBody | null>(null);
  let busy = $state(false);
  let input = $state<HTMLInputElement>();

  $effect(() => input?.select());

  async function submit(): Promise<void> {
    if (busy || !name.trim()) return;
    busy = true;
    error = null;
    try {
      error = await onsubmit(name.trim(), text);
    } finally {
      busy = false;
    }
    if (!error) oncancel();
  }
</script>

<Dialog title={t(kind === 'folder' ? 'explorer.new_dialog.folder_title' : 'explorer.new_dialog.text_title')} {oncancel}>
  <p class="mb-3 text-sm">{t('explorer.new_dialog.where', { folder: where })}</p>
  <label class="mb-3 flex flex-col gap-1 text-sm font-semibold text-ink">
    {t('explorer.new_dialog.name')}
    <input bind:this={input} bind:value={name} type="text" class="field rounded-xl px-3 py-2 font-normal" autocomplete="off"
      onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void submit(); } }} />
  </label>
  {#if kind === 'text'}
    <label class="mb-1 flex flex-col gap-1 text-sm font-semibold text-ink">
      {t('explorer.new_dialog.text')}
      <textarea bind:value={text} rows="6" class="field resize-y rounded-xl px-3 py-2 font-normal"></textarea>
    </label>
    <p class="text-2xs text-soft">{t('explorer.new_dialog.text_hint')}</p>
  {/if}
  {#if error}
    <p role="alert" class="mt-3 text-sm font-semibold text-bad">{t(`error.${known.includes(error.key) ? error.key : 'internal'}`)}</p>
  {/if}
  {#snippet actions()}
    <Button variant="ghost" onclick={oncancel}>{t('common.cancel')}</Button>
    <Button variant="primary" disabled={busy || !name.trim()} onclick={submit}>{t('explorer.new_dialog.create')}</Button>
  {/snippet}
</Dialog>
