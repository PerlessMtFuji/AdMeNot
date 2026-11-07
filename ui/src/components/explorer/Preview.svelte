<script lang="ts">
  import { fade } from 'svelte/transition';
  import { closeMorph } from '../../lib/explorer/morph';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { clock, formatBytes } from '../../lib/explorer/logic';
  import { NATIVE_IMAGE, PREFETCH_MAX } from '../../lib/explorer/peek';
  import { PhotoPrefetch } from '../../lib/explorer/prefetch';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { ERROR_KEYS, i18n, t } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import type { EntryMeta, EntryView } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon from './FileIcon.svelte';
  import MediaView from './MediaView.svelte';
  import MetaPanel from './MetaPanel.svelte';
  import PhotoView from './PhotoView.svelte';
  import TextView from './TextView.svelte';
  import PdfView from './PdfView.svelte';
  import SheetView from './SheetView.svelte';
  import { isSheet } from '../../lib/explorer/sheet';

  /** Okno podglądu nad eksploratorem: ciemne tło, pasek u góry, Esc / ← / → / Spacja. */
  let { ex, thumbs }: { ex: ExplorerController; thumbs: ThumbQueue } = $props();
  const entry = $derived(ex.previewEntry);
  const NEIGHBOURS = 5;
  /** Sąsiednie zdjęcia pobieramy po tej chwili, żeby szybkie strzałki ich nie zamawiały na próżno. */
  const PREFETCH_WAIT_MS = 200;

  let info = $state(false);
  let meta = $state<EntryMeta | null>(null);
  let decoded = $state<Record<string, number>>({});
  const displayMeta = $derived<EntryMeta | null>(entry ? { ...meta, ...decoded, size: entry.size, mtime: entry.mtime, path: entry.path } : null);
  let broken = $state<string | null>(null);  // plik, którego nie dało się zdekodować
  let box = $state<HTMLElement>();
  let media = $state<{ toggle(): void }>();
  /** „Kopiuj na komputer” przyjęte do kolejki — potwierdzenie (postęp jest na pasku zadań pod oknem). */
  let started = $state(false);
  const known: readonly string[] = ERROR_KEYS;
  const error = $derived(ex.state.error);
  const audioFailed = $derived(ex.state.playError && entry?.type === 'audio' && ex.state.playing?.path === entry.path);

  async function copy(): Promise<void> {
    started = false;
    started = await ex.copyPreview();
  }

  const view = $derived.by(() => {
    if (!entry || broken === entry.path) return 'unsupported';
    if (entry.type === 'image') return entry.url && NATIVE_IMAGE.includes(entry.ext.toLowerCase()) ? 'photo' : 'unsupported';
    if (entry.type === 'video' || entry.type === 'audio') return entry.url ? 'media' : 'unsupported';
    if (entry.ext.toLowerCase() === 'pdf' && entry.url) return 'pdf';
    if (isSheet(entry)) return 'sheet';
    return entry.type === 'text' ? 'text' : 'unsupported';
  });
  const showInfo = $derived(view === 'unsupported' || info);

  $effect(() => {
    const path = entry?.path;
    meta = null;
    decoded = {};
    started = false;
    if (!path) return;
    let stale = false;
    void ex.meta(path).then((m) => { if (!stale) meta = m; });
    return () => { stale = true; };
  });

  // Muzyka, której nie da się odtworzyć: jak nieobsługiwany format — ikona, metadane, kopiowanie (plan R9).
  $effect(() => { if (audioFailed && entry) broken = entry.path; });

  const files = $derived(ex.items.filter((e) => e.kind === 'file'));
  const at = $derived(files.findIndex((e) => e.path === entry?.path));
  const strip = $derived(entry?.type === 'image' ? files.slice(Math.max(0, at - NEIGHBOURS), at + NEIGHBOURS + 1) : []);
  /** Miniatura z pamięci galerii, a gdy jej tam nie ma — z serwera. */
  const thumbSrc = (url: string | null) => (url ? thumbs.get(url)?.src ?? url : null);

  const photos = new PhotoPrefetch();
  $effect(() => () => photos.clear());
  const isPhoto = (e: EntryView | undefined): e is EntryView & { url: string } =>
    !!e?.url && e.type === 'image' && e.size <= PREFETCH_MAX && NATIVE_IMAGE.includes(e.ext.toLowerCase());
  const photoUrl = $derived(entry?.url ? photos.get(entry.url) ?? entry.url : null);
  $effect(() => {
    if (at < 0) return;
    const current = isPhoto(files[at]) ? [files[at].url!] : [];
    const near = [files[at + 1], files[at - 1]].filter(isPhoto).map((e) => e.url);
    const timer = setTimeout(() => photos.keep(current, near), PREFETCH_WAIT_MS);
    return () => clearTimeout(timer);
  });

  const facts = $derived.by(() => {
    if (!entry) return [];
    const out = [formatBytes(entry.size, i18n.lang)];
    if (typeof displayMeta?.width === 'number' && typeof displayMeta?.height === 'number') out.push(`${displayMeta.width} × ${displayMeta.height}`);
    if (Number(displayMeta?.duration) > 0) out.push(clock(Number(displayMeta?.duration) / 1000));
    for (const k of ['artist', 'album']) if (typeof meta?.[k] === 'string') out.push(String(meta[k]));
    out.push(new Date(entry.mtime * 1000).toLocaleDateString(i18n.lang === 'pl' ? 'pl-PL' : 'en-US', { dateStyle: 'medium' }));
    return out;
  });

  function close(): void {
    const path = ex.state.preview;
    if (path === null) return;
    void closeMorph(path, () => ex.closePreview());
  }

  function onkey(e: KeyboardEvent): void {
    const el = e.target instanceof Element ? e.target : null;
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && !el?.closest('input, textarea, select')) {
      e.preventDefault();
      ex.next(e.key === 'ArrowRight' ? 1 : -1);
    } else if (e.key === ' ' && !el?.closest('button, input, textarea, select, a') && view === 'media') {
      e.preventDefault();
      media?.toggle();
    }
  }

  // Okno żyje w <body> (jak Dialog): przodek z transformacją nie zamknie `position: fixed` w swojej kolumnie.
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  $effect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box?.focus();
    return () => previous?.focus?.();
  });

  const NAV = 'absolute top-1/2 z-10 grid h-12 w-12 -translate-y-1/2 place-items-center rounded-full bg-black/40 text-white backdrop-blur-md transition duration-150 hover:bg-black/65 disabled:opacity-0';
</script>

<svelte:window onkeydown={onkey} />

{#if entry}
  <div use:portal bind:this={box} role="dialog" aria-modal="true" aria-label={t('explorer.preview.label', { name: entry.label ?? entry.name })}
    tabindex="-1" in:fade={{ duration: ms(DUR.micro) }}
    class="fixed inset-0 z-40 flex flex-col bg-[#07090d] text-white outline-none">
    <header class="relative z-10 flex flex-none items-center gap-3 border-b border-white/10 bg-black/35 px-5 py-3 backdrop-blur-xl">
      <div class="min-w-0 flex-1">
        <b class="block truncate text-md">{entry.label ?? entry.name}</b>
        <p class="truncate text-xs text-white/65">{facts.join(' · ')}</p>
      </div>
      {#if view !== 'unsupported'}
        <button type="button" aria-pressed={info} onclick={() => (info = !info)} aria-label={t('explorer.preview.info')}
          title={t('explorer.preview.info')}
          class="grid h-10 w-10 place-items-center rounded-full transition duration-150 {info ? 'bg-white/25' : 'bg-white/10 hover:bg-white/20'}">
          <Icon name="info" size={18} />
        </button>
      {/if}
      <Button size="sm" variant="primary" disabled={ex.state.starting} onclick={copy}>
        <Icon name="download" size={15} />{t('explorer.preview.copy')}
      </Button>
      <button type="button" onclick={close} aria-label={t('explorer.preview.close')} title={t('explorer.preview.close')}
        class="grid h-10 w-10 place-items-center rounded-full bg-white/10 transition duration-150 hover:bg-white/20">
        <Icon name="x" size={18} />
      </button>
    </header>

    {#if error || started || audioFailed || view === 'unsupported'}
      <div class="relative z-10 flex flex-none flex-col gap-2 px-5 pt-3">
        {#if error}
          <Banner tone="bad" icon="triangle-alert" title={t(`error.${known.includes(error.key) ? error.key : 'internal'}`)}>
            {#snippet actions()}<Button size="sm" variant="ghost" onclick={() => (ex.state.error = null)}>{t('common.close')}</Button>{/snippet}
          </Banner>
        {/if}
        {#if audioFailed}<Banner tone="bad" icon="triangle-alert">{t('explorer.preview.play_failed')}</Banner>{/if}
        {#if started}
          <Banner tone="ok" icon="check">
            {t('explorer.preview.copy_started')}
            {#snippet actions()}<Button size="sm" variant="ghost" onclick={() => (started = false)}>{t('common.close')}</Button>{/snippet}
          </Banner>
        {/if}
        {#if view === 'unsupported'}<Banner tone="info" icon="info">{t('explorer.preview.unsupported')}</Banner>{/if}
      </div>
    {/if}

    <div class="relative flex min-h-0 flex-1">
      <div class="relative min-w-0 flex-1">
        {#key entry.path}
          <div class="absolute inset-0" in:fade={{ duration: ms(DUR.enter) }}>
            {#if view === 'photo'}
              <PhotoView {entry} thumb={thumbSrc(entry.thumb)} full={photoUrl} onfail={() => (broken = entry.path)} />
            {:else if view === 'media'}
              <MediaView bind:this={media} {ex} {entry} meta={displayMeta} {thumbs} onmetadata={(m) => (decoded = m)} onfail={() => (broken = entry.path)} />
            {:else if view === 'text'}
              <TextView {ex} {entry} />
            {:else if view === 'pdf'}
              <PdfView {entry} />
            {:else if view === 'sheet'}
              <SheetView {ex} {entry} />
            {:else}
              <div class="absolute inset-0 flex flex-col items-center justify-center gap-4 p-8 text-center">
                <FileIcon kind="file" type={entry.type} ext={entry.ext} size={96} />
              </div>
            {/if}
          </div>
        {/key}
        <button type="button" class="{NAV} left-4" onclick={() => ex.next(-1)} disabled={at <= 0}
          aria-label={t('explorer.preview.prev')} title={t('explorer.preview.prev')}><Icon name="chevron-left" size={22} /></button>
        <button type="button" class="{NAV} right-4" onclick={() => ex.next(1)} disabled={at < 0 || at >= files.length - 1}
          aria-label={t('explorer.preview.next')} title={t('explorer.preview.next')}><Icon name="chevron-right" size={22} /></button>
      </div>
      {#if showInfo}
        <MetaPanel {entry} meta={displayMeta} onmap={(lat, lon) => ex.openMap(lat, lon)} />
      {/if}
    </div>

    {#if strip.length > 1}
      <nav aria-label={t('explorer.preview.neighbours')}
        class="relative z-10 flex flex-none justify-center gap-2 border-t border-white/10 bg-black/35 px-5 py-2.5 backdrop-blur-xl">
        {#each strip as n (n.path)}
          <button type="button" onclick={() => ex.openPreview(n.path)} aria-label={n.label ?? n.name}
            aria-current={n.path === entry.path ? 'true' : undefined}
            class="h-12 w-12 flex-none overflow-hidden rounded-[10px] transition duration-150 ease-out
              {n.path === entry.path ? 'scale-100 opacity-100 ring-2 ring-accent' : 'scale-90 opacity-60 hover:opacity-100'}">
            {#if n.thumb}<img src={thumbSrc(n.thumb)} alt="" draggable="false" decoding="async" class="h-full w-full object-cover" />
            {:else}<span class="grid h-full w-full place-items-center bg-white/10"><Icon name="image" size={18} /></span>{/if}
          </button>
        {/each}
      </nav>
    {/if}
  </div>
{/if}
