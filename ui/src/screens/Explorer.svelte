<script lang="ts">
  import { getContext, untrack } from 'svelte';
  import Crumbs from '../components/explorer/Crumbs.svelte';
  import FileList from '../components/explorer/FileList.svelte';
  import Gallery from '../components/explorer/Gallery.svelte';
  import Places from '../components/explorer/Places.svelte';
  import DropZone from '../components/explorer/DropZone.svelte';
  import EmptyState from '../components/explorer/EmptyState.svelte';
  import Menu from '../components/explorer/Menu.svelte';
  import MiniPlayer from '../components/explorer/MiniPlayer.svelte';
  import NewDialog from '../components/explorer/NewDialog.svelte';
  import Preview from '../components/explorer/Preview.svelte';
  import ProblemsDialog from '../components/explorer/ProblemsDialog.svelte';
  import SelectionBar from '../components/explorer/SelectionBar.svelte';
  import TaskBar from '../components/explorer/TaskBar.svelte';
  import type { Controller } from '../lib/controller';
  import { type ExplorerFilter, FILTERS, formatBytes } from '../lib/explorer/logic';
  import { mediaFetcher, ThumbQueue } from '../lib/explorer/thumbs';
  import { ERROR_KEYS, i18n, t, tp } from '../lib/i18n/index.svelte';
  import { enter } from '../lib/motion';
  import { zoomRun, zoomSnapshot } from '../lib/explorer/zoom';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const ex = ctl.explorer;
  const s = ex.state;
  const known: readonly string[] = ERROR_KEYS;
  const items = $derived(ex.items);
  const files = $derived(s.entries.filter((e) => e.kind === 'file'));
  const folders = $derived(s.entries.length - files.length);
  const bytes = $derived(files.reduce((sum, e) => sum + e.size, 0));
  const folderName = $derived(s.crumbs.at(-1)?.label ?? '');
  const errorText = $derived(s.error ? t(`error.${known.includes(s.error.key) ? s.error.key : 'internal'}`) : '');
  const TOGGLE = 'grid h-8 w-9 place-items-center rounded-[9px] transition duration-150';
  /** Odświeżanie „dziś/wczoraj”: co minutę i przy każdym odczycie folderu. */
  const CLOCK_MS = 60_000;

  // Miniatury galerii żyją tyle co ekran; przy wyjściu adresy `blob:` są zwalniane.
  const thumbs = new ThumbQueue(mediaFetcher);
  $effect(() => () => thumbs.clear());
  // Miniatury, które zawiodły przejściowo, próbują znowu po zmianie folderu i po powrocie telefonu.
  $effect(() => {
    void s.path;
    if (!s.offline) untrack(() => thumbs.retryFailed());
  });

  // Wejście w folder = przybliżenie (wyjście wyżej — odwrotnie). Zdjęcie starej zawartości robi się tuż przed
  // podmianą DOM (`$effect.pre`), ruch ruszają efekty po niej. Początek ruchu: ostatni klik w obszarze listy.
  let section: HTMLElement;
  let stage: HTMLElement;
  let clickAt: { x: number; y: number } | null = null;
  let zoomPath = untrack(() => s.path);
  let zoom: ReturnType<typeof zoomSnapshot> = null;
  function remember(e: PointerEvent): void {
    const box = stage?.getBoundingClientRect();
    clickAt = box ? { x: e.clientX - box.left, y: e.clientY - box.top } : null;
  }
  $effect.pre(() => {
    const path = s.path;
    untrack(() => {
      if (path === zoomPath) return;
      zoom?.ghost.remove();
      zoom = stage ? zoomSnapshot(section, stage, zoomPath, path, clickAt) : null;
      zoomPath = path;
      clickAt = null;
    });
  });
  $effect(() => {
    void s.path;
    untrack(() => {
      if (!zoom) return;
      zoomRun(stage, zoom);
      zoom = null;
    });
  });

  let now = $state(new Date());
  $effect(() => {
    void s.entries;
    now = new Date();
  });
  $effect(() => {
    const timer = setInterval(() => (now = new Date()), CLOCK_MS);
    return () => clearInterval(timer);
  });

  /** Skróty jak w Eksploratorze Windows — poza polami tekstowymi (tam Backspace i Ctrl+A edytują tekst). */
  function onkey(e: KeyboardEvent): void {
    if (s.preview !== null) return;  // okno podglądu ma własne skróty (Esc, ←, →, Spacja)
    const el = e.target instanceof Element ? e.target : null;
    if (el && (el.closest('input, textarea, select, [contenteditable="true"]') || el.closest('[role="dialog"]'))) return;
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === 'Backspace' && !mod) {
      e.preventDefault();
      void ex.up();
    } else if (mod && e.key.toLowerCase() === 'a') {
      e.preventDefault();
      ex.selectAll();
    } else if (mod && e.key.toLowerCase() === 'v') {
      e.preventDefault();
      void ex.paste();
    } else if (e.key === 'Escape') {
      ex.clear();
    } else if (e.key === 'F5') {
      e.preventDefault();
      void ex.refresh();
    }
  }

  let creating = $state<'folder' | 'text' | null>(null);
  const isFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
  /** Przeciąganie z Eksploratora Windows: strefa upuszczania; samo wgranie robi `explorer:drop` (ścieżki zna tylko most). */
  function ondragenter(e: DragEvent): void {
    if (!isFiles(e)) return;
    e.preventDefault();
    ex.dragOver(e.dataTransfer?.items?.length ?? null);
  }
  function ondragover(e: DragEvent): void {
    if (isFiles(e)) e.preventDefault();
  }
  function ondragleave(e: DragEvent): void {
    if (!e.relatedTarget) ex.dragEnd();
  }
  function ondrop(e: DragEvent): void {
    if (!isFiles(e)) return;
    e.preventDefault();
    // gdyby most nie przysłał `explorer:drop` (np. upuszczono coś bez plików), strefa nie może zostać
    setTimeout(() => ex.dragEnd(), DROP_GRACE_MS);
  }
  const DROP_GRACE_MS = 2000;
</script>

<svelte:window onkeydown={onkey} {ondragenter} {ondragover} {ondragleave} {ondrop} />

<main class="flex min-w-0 flex-1 flex-col gap-3 px-6 pt-5 pb-6">
  <h1 class="sr-only">{t('explorer.title', { name: s.device?.name ?? '' })}</h1>

  <header class="flex min-w-0 items-center gap-3">
    <Crumbs crumbs={s.crumbs} ongo={(p) => ex.go(p)} />
    {#key s.path}
      {#if files.length || folders}
        <span in:enter={{ y: 4 }} class="flex-none rounded-full bg-accent-soft px-2.5 py-0.5 text-2xs font-bold text-accent tabular-nums">
          {files.length ? tp('explorer.summary', files.length, { size: formatBytes(bytes, i18n.lang) }) : tp('explorer.folders', folders)}
        </span>
      {/if}
    {/key}
    {#if s.loading}<span class="spin flex-none" role="status" aria-label={t('explorer.loading')}></span>{/if}
    <span class="flex-1"></span>
    <div role="group" aria-label={t('explorer.view.label')}
      class="flex flex-none gap-0.5 rounded-xl bg-neutral-soft p-[3px] shadow-[var(--shadow-well)]">
      {#each [['grid', 'layout-grid'], ['list', 'list']] as const as [v, icon] (v)}
        <button type="button" aria-pressed={s.view === v} aria-label={t(`explorer.view.${v}`)} title={t(`explorer.view.${v}`)}
          onclick={() => ex.setView(v)} class="{TOGGLE} {s.view === v ? 'card text-ink' : 'text-mut hover:text-ink'}">
          <Icon name={icon} size={16} />
        </button>
      {/each}
    </div>
  </header>

  <div class="flex items-center gap-2.5">
    <label class="field flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2">
      <Icon name="search" size={15} class="text-soft" />
      <input type="search" class="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-soft"
        aria-label={t('explorer.search_label')} placeholder={t('explorer.search', { folder: folderName })}
        value={s.query} oninput={(e) => ex.setQuery(e.currentTarget.value)} />
    </label>
    <select class="field flex-none rounded-xl px-3 py-2 text-sm font-semibold text-ink" aria-label={t('explorer.filter.label')}
      value={s.filter} onchange={(e) => ex.setFilter(e.currentTarget.value as ExplorerFilter)}>
      {#each FILTERS as f (f)}<option value={f}>{t(`explorer.filter.${f}`)}</option>{/each}
    </select>
    <Menu title={t('explorer.new_menu.label')} menuLabel={t('explorer.new_menu.label')} disabled={s.locked}
      class="btn-secondary rounded-[10px] px-3 py-2 text-sm text-ink"
      items={[
        { id: 'folder', label: t('explorer.new_menu.folder'), onselect: () => (creating = 'folder') },
        { id: 'text', label: t('explorer.new_menu.text'), onselect: () => (creating = 'text') },
      ]}>
      <Icon name="plus" size={15} />{t('explorer.new')}<Icon name="chevron-down" size={14} />
    </Menu>
    <Menu title={t('explorer.upload_menu.label')} menuLabel={t('explorer.upload_menu.label')} disabled={s.locked}
      class="btn-primary rounded-[10px] px-3 py-2 text-sm text-white"
      items={[
        { id: 'files', label: t('explorer.upload_menu.files'), onselect: () => void ex.pickUpload('files') },
        { id: 'folder', label: t('explorer.upload_menu.folder'), onselect: () => void ex.pickUpload('folder') },
      ]}>
      <Icon name="upload" size={15} />{t('explorer.upload_here')}<Icon name="chevron-down" size={14} />
    </Menu>
  </div>

  {#if s.offline}
    <Banner tone="warn" icon="wifi-off" title={t('explorer.offline.title')}>{t('explorer.offline.text')}</Banner>
  {/if}
  {#if s.error}
    <Banner tone="bad" icon="triangle-alert" title={errorText}>
      {#snippet actions()}<Button size="sm" variant="ghost" onclick={() => (s.error = null)}>{t('common.close')}</Button>{/snippet}
    </Banner>
  {/if}
  {#if s.clipboardEmpty}
    <Banner tone="info" icon="info">
      {t('explorer.clipboard_empty')}
      {#snippet actions()}<Button size="sm" variant="ghost" onclick={() => ex.dismissClipboard()}>{t('common.close')}</Button>{/snippet}
    </Banner>
  {/if}
  {#if s.leftovers > 0}
    <Banner tone="ok" icon="check">
      {tp('explorer.leftovers', s.leftovers)}
      {#snippet actions()}<Button size="sm" variant="ghost" onclick={() => ex.dismissLeftovers()}>{t('common.close')}</Button>{/snippet}
    </Banner>
  {/if}

  <div class="flex min-h-0 flex-1 gap-3.5">
    <Places places={s.places} recent={s.recent} path={s.path} storage={s.storage} ongo={(p) => ex.go(p)} />
    <section bind:this={section} aria-label={folderName} onpointerdown={remember}
      class="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl card px-2 pt-3 pb-1.5">
      <div bind:this={stage} class="relative flex min-h-0 flex-1 flex-col">
        {#if s.locked}
          <EmptyState kind="locked" />
        {:else}
          {#if s.view === 'grid'}
            <Gallery {ex} {items} {now} {thumbs} />
          {:else}
            <FileList {ex} {items} {now} />
          {/if}
          {#if !items.length && !s.loading}
            <div class="pointer-events-none absolute inset-0 grid place-items-center">
              <EmptyState kind={s.offline ? 'offline' : s.entries.length ? 'filter' : 'folder'} />
            </div>
          {/if}
          {#if s.skipped > 0}<p class="px-3 pt-1 text-2xs text-soft">{tp('explorer.skipped', s.skipped)}</p>{/if}
        {/if}
      </div>
      {#if s.drop}<DropZone drop={s.drop} folder={folderName} free={s.storage ? Math.max(0, s.storage.total - s.storage.used) : null} />{/if}
    </section>
  </div>

  <SelectionBar {ex} />
  <MiniPlayer {ex} {thumbs} />
  <TaskBar {ex} />
</main>

{#if creating}
  <NewDialog kind={creating} where={folderName} oncancel={() => (creating = null)}
    onsubmit={(name, text) => (creating === 'folder' ? ex.newFolder(name) : ex.newText(name, text))} />
{/if}
{#if s.preview !== null}<Preview {ex} {thumbs} />{/if}
{#if s.problems}<ProblemsDialog {ex} problems={s.problems} />{/if}
