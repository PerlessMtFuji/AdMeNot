<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import type { PhoneBadge } from '../lib/logic';
  import type { RepairTab } from '../lib/state.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  // appsCount: null = bez znacznika (tryb ręczny / nic niewybrane / 0).
  type Props = { value: RepairTab; onchange: (tab: RepairTab) => void; appsCount: number | null; phone: PhoneBadge };
  let { value, onchange, appsCount, phone }: Props = $props();

  const TABS: RepairTab[] = ['apps', 'phone'];

  // Strzałki przełączają zakładki (roving tabindex); zdarzenie nie może dotrzeć do klawiatury tabeli eksperta.
  function onkey(e: KeyboardEvent, tab: RepairTab) {
    if (!e.key.startsWith('Arrow')) return;
    // Alt/Ctrl/Meta + strzałka (np. Alt+← = wstecz w przeglądarce): nic nie robimy, niech obsłuży to przeglądarka/system.
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    e.stopPropagation();
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const other: RepairTab = tab === 'apps' ? 'phone' : 'apps';
    onchange(other);
    document.getElementById(`repair-tab-${other}`)?.focus();
  }
</script>

<div role="tablist" aria-label={t('repair_tabs.label')}
  class="flex gap-1 border-b border-line whitespace-nowrap">
  {#each TABS as tab (tab)}
    {@const on = tab === value}
    <button type="button" role="tab" id="repair-tab-{tab}" aria-selected={on} aria-controls="repair-panel-{tab}"
      tabindex={on ? 0 : -1} onclick={() => onchange(tab)} onkeydown={(e) => onkey(e, tab)}
      class="-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-semibold whitespace-nowrap transition duration-150 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]
        {on ? 'border-accent text-accent' : 'border-transparent text-mut hover:text-ink'}">
      {t(`repair_tabs.${tab}`)}
      {#if tab === 'apps' && appsCount != null}
        <Pill tone="warn">{appsCount}</Pill>
      {:else if tab === 'phone'}
        {#if phone.kind === 'count'}
          <Pill tone="warn">{phone.count}</Pill>
        {:else if phone.kind === 'ok'}
          <span role="img" aria-label={t('repair_tabs.phone_ok')}><Pill tone="ok"><Icon name="check" size={12} strokeWidth={3} /></Pill></span>
        {:else}
          <span role="img" aria-label={t('repair_tabs.phone_unknown')}><Pill tone="neutral">?</Pill></span>
        {/if}
      {/if}
    </button>
  {/each}
</div>
