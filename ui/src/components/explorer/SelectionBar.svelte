<script lang="ts">
  import { fly } from 'svelte/transition';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { formatBytes } from '../../lib/explorer/logic';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import Menu from './Menu.svelte';

  /** Pasek zaznaczenia: sprężyście wjeżdża z dołu; „Kopiuj” do zapamiętanego folderu na komputerze. */
  let { ex }: { ex: ExplorerController } = $props();
  const s = $derived(ex.state);
  const size = $derived(s.entries.reduce((sum, e) => (e.kind === 'file' && s.selected.has(e.path) ? sum + e.size : sum), 0));
  const destName = $derived(s.dest ? (s.dest.split(/[\\/]/).filter(Boolean).pop() ?? s.dest) : '');
  const spring = (t: number) => 1 - Math.cos(t * Math.PI * 4.5) * Math.exp(-t * 6);
</script>

{#if s.selected.size && !s.barHeld && s.preview === null && !s.loading}
  <section aria-label={t('explorer.selection.label')} transition:fly={{ y: 40, duration: ms(DUR.success), easing: spring }}
    class="flex flex-none flex-wrap items-center gap-3 rounded-2xl card px-4 py-2.5">
    <b class="text-sm text-ink tabular-nums">
      {tp('explorer.selection.count', s.selected.size)}{size > 0 ? ` · ${formatBytes(size, i18n.lang)}` : ''}
    </b>
    <span class="flex-1"></span>
    <button type="button" onclick={() => ex.pickDest()} title={s.dest ? t('explorer.selection.dest_title') : undefined}
      class="inline-flex min-w-0 max-w-[240px] items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1.5 text-sm font-semibold text-accent
        transition duration-150 hover:brightness-95">
      <Icon name="folder" size={15} />
      <span class="truncate">{s.dest ? destName : t('explorer.selection.dest_pick')}</span>
    </button>
    <Button size="sm" variant="primary" disabled={s.starting} onclick={() => ex.copySelected()}>
      <Icon name="download" size={15} />{t('explorer.selection.copy')}
    </Button>
    <Menu up label={t('explorer.selection.more')} title={t('explorer.selection.more')} menuLabel={t('explorer.selection.more')}
      class="btn-secondary h-[34px] w-[34px] rounded-[10px] text-ink" items={[
        { id: 'verify', label: t('explorer.selection.verify'), sub: t('explorer.selection.verify_sub'), onselect: () => void ex.copySelected(true) },
      ]}>
      <span aria-hidden="true">⋯</span>
    </Menu>
    <Button size="sm" variant="ghost" onclick={() => ex.clear()}>{t('explorer.selection.clear')}</Button>
  </section>
{/if}
