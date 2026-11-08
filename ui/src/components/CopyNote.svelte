<script lang="ts">
  import Pencil from '@lucide/svelte/icons/pencil';
  import StickyNote from '@lucide/svelte/icons/sticky-note';
  import { getContext, tick } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { CopyView } from '../lib/types';
  import Button from '../ui/Button.svelte';

  // Notatka serwisanta do kopii danych: w Historii i w czasie kopiowania. Zapis od razu w kopii
  // (`set_transfer_note`); pusta notatka ją usuwa.
  type Props = { copy: CopyView; /** Podpis przycisku dodawania (domyślnie „Dodaj notatkę”). */ addLabel?: string };
  let { copy, addLabel }: Props = $props();
  const ctl = getContext<Controller>('ctl');
  const MAX = 2000;
  let editing = $state(false);
  let draft = $state('');
  let saving = $state(false);
  let area = $state<HTMLTextAreaElement | null>(null);

  /** Otwiera pole edycji (menu wiersza Historii: „Notatka”). */
  export async function edit(): Promise<void> {
    draft = copy.note ?? '';
    editing = true;
    await tick();
    area?.focus();
  }

  async function save(): Promise<void> {
    saving = true;
    const ok = await ctl.setTransferNote(copy.id, draft.trim() || null);
    saving = false;
    if (ok) editing = false;  // błąd: Banner błędu, tekst zostaje w polu
  }

  function key(e: KeyboardEvent): void {
    if (e.key === 'Escape') { e.stopPropagation(); editing = false; }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void save(); }
  }
</script>

{#if editing}
  <div class="mt-1.5 flex flex-col gap-1.5">
    <textarea bind:this={area} bind:value={draft} maxlength={MAX} rows="3" onkeydown={key}
      aria-label={t('transfer.note.label')} placeholder={t('transfer.note.placeholder')}
      class="w-full resize-y rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-ink"></textarea>
    <div class="flex items-center gap-2">
      <Button variant="primary" size="sm" disabled={saving} onclick={save}>{t('common.save')}</Button>
      <Button variant="ghost" size="sm" onclick={() => (editing = false)}>{t('common.cancel')}</Button>
    </div>
  </div>
{:else if copy.note}
  <div class="mt-1 flex items-start gap-1.5 text-sm text-mut">
    <span class="mt-0.5 flex-none text-soft" aria-hidden="true"><StickyNote size={14} /></span>
    <p class="min-w-0 flex-1 whitespace-pre-line break-words" data-testid="copy-note">{copy.note}</p>
    <button type="button" class="flex flex-none items-center gap-1 font-semibold text-accent hover:underline"
      onclick={edit}><Pencil size={13} />{t('transfer.note.edit')}</button>
  </div>
{:else}
  <button type="button" class="mt-1 flex items-center gap-1 text-sm font-semibold text-accent hover:underline"
    onclick={edit}><StickyNote size={14} />{addLabel ?? t('transfer.note.add')}</button>
{/if}
