<script lang="ts">
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { clock } from '../../lib/explorer/logic';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { t } from '../../lib/i18n/index.svelte';
  import { reducedMotion } from '../../lib/motion';
  import type { EntryMeta, EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon from './FileIcon.svelte';

  /** Film (`<video>`, poświata z bieżącej klatki) albo muzyka (okładka, wspólny odtwarzacz z mini-odtwarzaczem). */
  type Props = { ex: ExplorerController; entry: EntryView; meta: EntryMeta | null; thumbs: ThumbQueue; onfail: () => void;
    onmetadata?: (meta: Record<string, number>) => void };
  let { ex, entry, meta, thumbs, onfail, onmetadata }: Props = $props();

  const GLOW_MS = 250;
  const GLOW_W = 48;
  const GLOW_H = 27;
  const isVideo = $derived(entry.type === 'video');
  const current = $derived(ex.state.playing?.path === entry.path);
  let video = $state<HTMLVideoElement>();
  let canvas = $state<HTMLCanvasElement>();
  const media = $derived<HTMLMediaElement | undefined>(isVideo ? video : current ? ex.audio.el : undefined);

  let paused = $state(true);
  let time = $state(0);
  let length = $state(0);
  let buffered = $state(0);

  // Czas trwania z metadanych (ms z MediaStore), zanim element go pozna.
  const metaLength = $derived(Number(meta?.duration) > 0 ? Number(meta?.duration) / 1000 : 0);
  const total = $derived(length > 0 && Number.isFinite(length) ? length : metaLength);
  /** Most podaje adres okładki każdemu MP3/FLAC; plik bez okładki odpowiada błędem. */
  let noCover = $state(false);
  const cover = $derived(noCover ? null : entry.thumb);
  const color = $derived((cover ? thumbs.get(cover)?.color : '') || 'var(--glow-accent)');

  function sync(): void {
    const el = media;
    paused = el ? el.paused : true;
    time = el ? el.currentTime : 0;
    length = el ? el.duration : 0;
    buffered = el && el.buffered.length ? el.buffered.end(el.buffered.length - 1) : 0;
  }
  /** Kodek obrazu, którego okno nie obsługuje (np. MPEG-4 Part 2): dźwięk gra, obrazu nie ma. */
  let noPicture = $state(false);
  function loaded(): void {
    noPicture = !!video && !video.videoWidth;
    if (!video || !video.videoWidth || !video.videoHeight) return;
    onmetadata?.({ width: video.videoWidth, height: video.videoHeight,
      ...(Number.isFinite(video.duration) ? { duration: video.duration * 1000 } : {}) });
  }
  $effect(() => {
    const el = media;
    sync();
    if (!el) return;
    const events = ['play', 'pause', 'ended', 'timeupdate', 'durationchange', 'progress', 'seeked', 'loadedmetadata'];
    for (const name of events) el.addEventListener(name, sync);
    return () => { for (const name of events) el.removeEventListener(name, sync); };
  });

  // Film rusza sam, więc grająca w tle muzyka musi ustąpić.
  $effect(() => { if (isVideo) ex.audio.pause(); });

  // Poświata filmu: mała kopia bieżącej klatki, rozmyta w CSS. Przy reduced-motion tylko po przewinięciu.
  function paint(): void {
    const ctx = canvas?.getContext('2d');
    if (!ctx || !video || video.readyState < 2) return;
    try {
      ctx.drawImage(video, 0, 0, GLOW_W, GLOW_H);
    } catch {
      // klatka niedostępna (strumień urwany) — poświata zostaje jak była
    }
  }
  $effect(() => {
    if (!isVideo || !video) return;
    const el = video;
    const events = ['loadeddata', 'seeked'];
    for (const name of events) el.addEventListener(name, paint);
    const timer = reducedMotion() ? undefined : setInterval(paint, GLOW_MS);
    return () => {
      for (const name of events) el.removeEventListener(name, paint);
      clearInterval(timer);
    };
  });

  /** Odtwarza / wstrzymuje (Spacja w oknie podglądu woła to samo). */
  export function toggle(): void {
    if (isVideo) {
      if (!video) return;
      if (video.paused) void video.play().catch(() => {});
      else video.pause();
    } else {
      void ex.toggleTrack(entry);
    }
  }

  function seek(e: Event): void {
    const to = Number((e.currentTarget as HTMLInputElement).value);
    if (media) media.currentTime = to;
    time = to;
  }

  async function skip(): Promise<void> {
    await ex.skipTrack();
  }

  const ICON_BTN = 'grid h-11 w-11 place-items-center rounded-full bg-white/12 text-white transition duration-150 hover:bg-white/22 disabled:opacity-40';
</script>

<div class="absolute inset-0 grid place-items-center">
  {#if isVideo}
    <canvas bind:this={canvas} width={GLOW_W} height={GLOW_H} aria-hidden="true"
      class="pointer-events-none absolute inset-0 h-full w-full scale-125 opacity-70 blur-[40px] saturate-[1.4]"></canvas>
    <!-- svelte-ignore a11y_media_has_caption -->
    <div class="absolute inset-0 bottom-[110px]">
      <video bind:this={video} src={entry.url} preload="metadata" playsinline autoplay onerror={onfail} onloadedmetadata={loaded}
        onclick={toggle} class="absolute inset-0 h-full w-full cursor-pointer object-contain"></video>
      {#if noPicture}
        <div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-4 p-8 text-center">
          <FileIcon kind="file" type="video" ext={entry.ext} size={96} />
          <p class="max-w-md text-sm text-white/80">{t('explorer.preview.no_picture')}</p>
        </div>
      {/if}
    </div>
  {:else}
    <div class="relative mb-24 grid place-items-center">
      <span aria-hidden="true" class="breathe absolute -inset-10 rounded-full opacity-60 blur-[48px]"
        class:running={!paused} style:background={color}></span>
      <div class="relative grid h-[280px] w-[280px] place-items-center overflow-hidden rounded-[28px] text-white
        shadow-[0_24px_60px_-20px_rgb(0_0_0/.8)]"
        style:background={cover ? undefined : 'linear-gradient(135deg,#a78bfa,#6d28d9)'}>
        {#if cover}
          <img src={cover} alt="" draggable="false" class="h-full w-full object-cover" onerror={() => (noCover = true)} />
        {:else}
          <Icon name="music" size={96} strokeWidth={1.5} />
        {/if}
      </div>
    </div>
  {/if}

  <div class="absolute inset-x-0 bottom-0 flex flex-col gap-2 bg-gradient-to-t from-black/70 to-transparent px-8 pt-10 pb-5">
    <div class="relative h-5">
      <span class="absolute top-1/2 right-0 left-0 h-1 -translate-y-1/2 rounded-full bg-white/15"></span>
      <!-- bufor: ile już pobrano -->
      <span data-buffered class="absolute top-1/2 left-0 h-1 w-full origin-left -translate-y-1/2 rounded-full bg-white/30"
        style:transform="translateY(-50%) scaleX({total > 0 ? Math.min(1, buffered / total) : 0})"></span>
      <span class="absolute top-1/2 left-0 h-1 w-full origin-left -translate-y-1/2 rounded-full bg-accent"
        style:transform="translateY(-50%) scaleX({total > 0 ? Math.min(1, time / total) : 0})"></span>
      <input type="range" min="0" max={total || 0} step="0.1" value={time} disabled={!media || !total} oninput={seek}
        aria-label={t('explorer.preview.seek')} class="absolute inset-0 h-5 w-full cursor-pointer opacity-0" />
    </div>
    <div class="flex items-center gap-3 text-white">
      <button type="button" onclick={toggle} aria-label={t(paused ? 'explorer.preview.play' : 'explorer.preview.pause')}
        class={ICON_BTN}><Icon name={paused ? 'play' : 'pause'} size={18} class={paused ? 'fill-current' : ''} /></button>
      {#if !isVideo}
        <button type="button" onclick={skip} disabled={!ex.nextTrack || !current} aria-label={t('explorer.preview.next_track')}
          title={t('explorer.preview.next_track')} class={ICON_BTN}><Icon name="skip-forward" size={18} /></button>
      {/if}
      <span class="text-xs tabular-nums text-white/80">{clock(time)}{total ? ` / ${clock(total)}` : ''}</span>
    </div>
  </div>
</div>

<style>
  .breathe { animation: breathe 3.2s ease-in-out infinite paused; }
  .breathe.running { animation-play-state: running; }
  @keyframes breathe { 0%, 100% { transform: scale(.92); opacity: .35; } 50% { transform: scale(1.06); opacity: .7; } }
  @media (prefers-reduced-motion: reduce) { .breathe { animation: none; } }
</style>
