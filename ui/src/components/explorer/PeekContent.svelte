<script lang="ts">
  import { untrack } from 'svelte';
  import { BARS, type AudioPlayer } from '../../lib/explorer/audio';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { clock, formatBytes } from '../../lib/explorer/logic';
  import { drawFirstPage } from '../../lib/explorer/pdf';
  import { PEEK_FULL_WAIT_MS, peekSize, PREFETCH_MAX, type PeekKind } from '../../lib/explorer/peek';
  import { colName } from '../../lib/explorer/sheet';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { i18n, tp } from '../../lib/i18n/index.svelte';
  import { DUR, ms, reducedMotion } from '../../lib/motion';
  import type { EntryView, SheetHeadView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon from './FileIcon.svelte';

  /** Treść dymka dla jednego pliku; `PeekBubble` zakłada ją od nowa przy każdym pliku, więc odmontowanie
   *  przerywa pobieranie. `ontake` — dźwięk ruszył; `onsize` — znane wymiary treści; `onfail` — pliku nie da się pokazać
   *  (dymek znika po cichu); `sweep` — dymek z przejazdu, pełne zdjęcie czeka `PEEK_FULL_WAIT_MS`. */
  type Props = { ex: ExplorerController; entry: EntryView; kind: PeekKind; sweep: boolean; thumbs: ThumbQueue; audio: () => AudioPlayer;
    ontake: () => void; onsize: (w: number, h: number) => void; onfail: () => void };
  let { ex, entry, kind, sweep, thumbs, audio, ontake, onsize, onfail }: Props = $props();

  const IDLE = 0.12;
  /** Most podaje adres okładki każdemu MP3/FLAC; plik bez okładki odpowiada błędem. */
  let noCover = $state(false);
  const cover = $derived(noCover ? null : entry.thumb);
  const wantFull = $derived(kind === 'photo' && entry.size <= PREFETCH_MAX);
  /** Miniatura z pamięci galerii. Z serwera tylko wtedy, gdy pełnego pliku nie będzie: tego odczytu nie da się przerwać,
   *  a dla PNG to czytanie całego pliku. */
  const thumb = $derived(cover ? thumbs.get(cover) : null);
  const thumbSrc = $derived(cover ? thumb?.src ?? (wantFull ? undefined : cover) : undefined);
  /** Klatka filmu: galeria trzyma ją pod adresem pliku, a sam adres pliku nie jest obrazem. */
  const frame = $derived(kind === 'video' && entry.url ? thumbs.get(entry.url)?.src : undefined);

  let duration = $state(0);
  function metadata(el: HTMLMediaElement): void {
    if (Number.isFinite(el.duration) && el.duration > 0) duration = el.duration;
  }

  // Zdjęcie: samo odpięcie <img> z DOM nie przerywa pobierania, zdjęcie `src` — tak.
  let sharp = $state(false);
  let fullDue = $state(untrack(() => !sweep));
  $effect(() => {
    if (!wantFull || fullDue) return;
    const wait = setTimeout(() => (fullDue = true), PEEK_FULL_WAIT_MS);
    return () => clearTimeout(wait);
  });
  /** Pokazuje zdjęcie dopiero zdekodowane, żeby dekodowanie nie trafiło w klatkę. Odrzucenie po wczytaniu to tylko brak
   *  tej gwarancji, a zdjęty `src` to koniec dymka. */
  function fullLoaded(e: Event): void {
    const el = e.currentTarget as HTMLImageElement;
    void el.decode().catch(() => {}).then(() => {
      if (!el.hasAttribute('src')) return;
      onsize(el.naturalWidth, el.naturalHeight);
      sharp = true;
    });
  }
  function imageSize(e: Event): void {
    const el = e.currentTarget as HTMLImageElement;
    onsize(el.naturalWidth, el.naturalHeight);
  }
  function cancelLoad(node: HTMLImageElement) {
    return { destroy: () => node.removeAttribute('src') };
  }
  /** Zdjęty `src` (`cancelLoad`) Chromium zgłasza jako `error` już po zamknięciu dymka; wtedy właściwości dymka
   *  (`kind`, `entry`) czytają nieistniejący wpis i rzucają — zdarzenia po końcu dymka są pomijane. */
  let alive = true;
  $effect(() => () => { alive = false; });
  function thumbFailed(): void {
    if (!alive) return;
    noCover = true;
    if (kind === 'photo' && !wantFull) onfail();
  }

  // Film: przy końcu dymka strumień z telefonu musi się urwać, sam `pause` go nie zamyka.
  let video = $state<HTMLVideoElement>();
  let noPicture = $state(false);
  let noFrame = $state(true);
  let progress = $state(0);
  function videoLoaded(el: HTMLVideoElement): void {
    noPicture = !el.videoWidth;
    onsize(el.videoWidth, el.videoHeight);
    metadata(el);
  }
  function videoTime(el: HTMLVideoElement): void {
    progress = el.duration > 0 && Number.isFinite(el.duration) ? el.currentTime / el.duration : 0;
  }
  $effect(() => {
    const el = video;
    if (!el) return;
    // Muzyka staje dopiero przy pierwszym `playing`: typ, którego okno nie zagra, nie robi w niej dziury.
    el.addEventListener('playing', ontake, { once: true });
    void el.play().catch(() => {});
    return () => {
      el.removeEventListener('playing', ontake);
      el.pause();
      el.removeAttribute('src');
      el.load();
    };
  });

  // Muzyka: własny odtwarzacz dymka, nie ten z kolejką. Między dymkami `stop` zwalnia źródło.
  let paused = $state(true);
  let bars: HTMLElement[] = [];
  $effect(() => {
    if (kind !== 'audio' || !entry.url) return;
    const player = audio();
    const el = player.el;
    const sync = () => { paused = el.paused; };
    const loaded = () => metadata(el);
    const events = ['play', 'pause', 'ended'];
    for (const name of events) el.addEventListener(name, sync);
    el.addEventListener('loadedmetadata', loaded);
    el.addEventListener('playing', ontake, { once: true });
    player.onerror = onfail;
    player.load(entry.url);
    void player.play().catch(() => {});
    return () => {
      for (const name of events) el.removeEventListener(name, sync);
      el.removeEventListener('loadedmetadata', loaded);
      el.removeEventListener('playing', ontake);
      player.onerror = null;
      player.stop();
    };
  });

  // Słupki: pętla rAF tylko gdy gra, jest analizator i ruch jest dozwolony; poza tym stoją płasko.
  $effect(() => {
    if (kind !== 'audio' || paused || reducedMotion() || !audio().analysable) {
      bars.forEach((b) => { if (b) b.style.transform = `scaleY(${IDLE})`; });
      return;
    }
    const player = audio();
    let frame = requestAnimationFrame(function tick() {
      const levels = player.levels();
      for (let i = 0; i < BARS; i++) if (bars[i]) bars[i].style.transform = `scaleY(${Math.max(IDLE, levels[i])})`;
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  });

  // PDF: odrzucenie po przerwaniu to zwykłe odjechanie, a nie zły plik.
  let canvas = $state<HTMLCanvasElement>();
  let drawn = $state(false);
  $effect(() => {
    if (!canvas || !entry.url) return;
    const stop = new AbortController();
    drawFirstPage(entry.url, canvas, peekSize('pdf').w, stop.signal).then(
      () => { if (!stop.signal.aborted) drawn = true; },
      () => { if (!stop.signal.aborted) onfail(); },
    );
    return () => stop.abort();
  });

  // Tekst: wynik, który przyszedł po zmianie pliku, jest porzucany.
  let text = $state('');
  $effect(() => {
    if (kind !== 'text') return;
    let stale = false;
    void ex.textHead(entry.path).then((head) => {
      if (stale) return;
      if (head) text = head.text;
      else onfail();
    });
    return () => { stale = true; };
  });

  // Arkusz: początek pierwszego arkusza; plik z hasłem albo nie do odczytania — dymek znika jak przy błędzie.
  const SHEET_COLS = 8;
  let head = $state.raw<SheetHeadView | null>(null);
  const headCols = $derived(Math.min(SHEET_COLS, Math.max(0, ...(head?.rows ?? []).map((r) => r.length))));
  $effect(() => {
    if (kind !== 'sheet') return;
    let stale = false;
    void ex.sheetHead(entry.path).then((r) => {
      if (stale) return;
      if (r && !('problem' in r) && r.rows.length) head = r;
      else onfail();
    });
    return () => { stale = true; };
  });
</script>

{#snippet typeIcon()}
  <div data-peek-icon class="absolute inset-0 grid place-items-center bg-surface-2">
    <FileIcon kind="file" type={entry.type} ext={entry.ext} size={72} />
  </div>
{/snippet}

<div class="flex h-full flex-col">
  <div class="relative min-h-0 flex-1 overflow-hidden bg-surface-2">
    {#if kind === 'photo'}
      <div class="absolute inset-0" style:background={thumb?.color || undefined}>
        {#if thumbSrc}
          <img use:cancelLoad src={thumbSrc} alt="" draggable="false" onerror={thumbFailed} class="absolute inset-0 h-full w-full object-contain"
            onload={imageSize} />
        {/if}
        {#if wantFull && fullDue}
          <img use:cancelLoad src={entry.url} alt="" draggable="false" decoding="async" onload={fullLoaded} onerror={onfail}
            class="absolute inset-0 h-full w-full object-contain transition-opacity {sharp ? '' : 'opacity-0'}"
            style:transition-duration="{ms(DUR.micro)}ms" />
        {/if}
      </div>
      {#if !thumbSrc && !sharp}{@render typeIcon()}{/if}
    {:else if kind === 'video'}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={video} src={entry.url} poster={frame} preload="metadata" playsinline onerror={onfail}
        onloadedmetadata={(e) => videoLoaded(e.currentTarget)} onloadeddata={() => (noFrame = false)} ontimeupdate={(e) => videoTime(e.currentTarget)}
        class="absolute inset-0 h-full w-full bg-black object-contain"></video>
      <!-- Plakat nie zdradza swoich wymiarów, a do metadanych filmu bywa daleko. -->
      {#if frame}
        <img src={frame} alt="" hidden onload={imageSize} />
      {/if}
      {#if noPicture || (noFrame && !frame)}{@render typeIcon()}{/if}
      <span class="absolute inset-x-0 bottom-0 h-[3px] origin-left bg-accent" style:transform="scaleX({progress})"></span>
    {:else if kind === 'audio'}
      <div class="absolute inset-0 flex items-center gap-4 px-4">
        <div class="grid h-28 w-28 flex-none place-items-center overflow-hidden rounded-[14px] text-white"
          style:background={thumbSrc ? undefined : 'linear-gradient(135deg,#a78bfa,#6d28d9)'}>
          {#if thumbSrc}
            <img use:cancelLoad src={thumbSrc} alt="" draggable="false" onerror={thumbFailed} class="h-full w-full object-cover" />
          {:else}
            <Icon name="music" size={44} strokeWidth={1.5} />
          {/if}
        </div>
        <div class="flex h-16 flex-1 items-end justify-center gap-[2px]">
          {#each Array.from({ length: BARS }, (_, i) => i) as i (i)}
            <span bind:this={bars[i]} class="h-full w-[3px] origin-bottom rounded-full bg-accent" style:transform="scaleY({IDLE})"></span>
          {/each}
        </div>
      </div>
    {:else if kind === 'pdf'}
      <canvas bind:this={canvas} class="block w-full bg-white"></canvas>
      {#if !drawn}{@render typeIcon()}{/if}
    {:else if kind === 'sheet' && head}
      <table data-peek-sheet class="absolute inset-0 w-full table-fixed border-collapse bg-surface text-2xs text-ink">
        <thead><tr class="bg-surface-2 text-mut">
          <th class="w-8 border border-line"></th>
          {#each Array.from({ length: headCols }, (_, c) => c) as c (c)}<th class="border border-line px-1 font-semibold">{colName(c)}</th>{/each}
        </tr></thead>
        <tbody>
          {#each head.rows as row, r (r)}
            <tr>
              <td class="border border-line bg-surface-2 pr-1 text-right text-mut tabular-nums">{r + 1}</td>
              {#each Array.from({ length: headCols }, (_, c) => c) as c (c)}
                <td class="truncate border border-line px-1 leading-5 {r === 0 ? 'font-semibold' : ''}">{row[c] ?? ''}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    {:else if text}
      <pre class="mono absolute inset-0 overflow-hidden p-3 text-xs leading-relaxed break-words whitespace-pre-wrap text-ink">{text}</pre>
    {:else}
      {@render typeIcon()}
    {/if}
  </div>
  <footer class="flex flex-none items-center gap-3 px-3 py-2">
    <b class="min-w-0 flex-1 truncate text-sm text-ink">{entry.label ?? entry.name}</b>
    <span class="flex-none text-2xs text-mut tabular-nums">
      {head && head.names.length > 1 ? `${tp('explorer.preview.sheet_count', head.names.length)} · ` : ''}{formatBytes(entry.size, i18n.lang)}{duration ? ` · ${clock(duration)}` : ''}
    </span>
  </footer>
</div>
