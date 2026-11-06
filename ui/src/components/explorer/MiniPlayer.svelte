<script lang="ts">
  import { fly } from 'svelte/transition';
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { BARS } from '../../lib/explorer/audio';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { t } from '../../lib/i18n/index.svelte';
  import { DUR, ms, reducedMotion } from '../../lib/motion';
  import Icon from '../../ui/Icon.svelte';

  /** Mini-odtwarzacz nad paskiem zadań: gra dalej po zamknięciu podglądu muzyki. Słupki z AnalyserNode
   *  (24, requestAnimationFrame; wyłączone przy reduced-motion), okładka „oddycha” poświatą w swoim kolorze. */
  let { ex, thumbs }: { ex: ExplorerController; thumbs: ThumbQueue } = $props();
  const playing = $derived(ex.state.playing);
  const el = $derived(ex.audio.el);
  let paused = $state(true);
  let progress = $state(0);
  let bars: HTMLElement[] = [];
  /** Okładka, której plik nie ma (adres dostaje każdy MP3/FLAC). */
  let missing = $state<string | null>(null);
  const cover = $derived(playing?.cover && playing.cover !== missing ? playing.cover : null);
  const color = $derived((cover ? thumbs.get(cover)?.color : '') || 'var(--glow-accent)');
  const IDLE = 0.12;

  function sync(): void {
    paused = el.paused;
    progress = el.duration > 0 && Number.isFinite(el.duration) ? el.currentTime / el.duration : 0;
  }
  $effect(() => {
    sync();
    const events = ['play', 'pause', 'ended', 'timeupdate', 'durationchange'];
    for (const name of events) el.addEventListener(name, sync);
    return () => { for (const name of events) el.removeEventListener(name, sync); };
  });

  // Słupki: pętla rAF tylko gdy gra, jest analizator i ruch jest dozwolony; poza tym stoją płasko.
  $effect(() => {
    const flat = () => bars.forEach((b) => { if (b) b.style.transform = `scaleY(${IDLE})`; });
    if (paused || reducedMotion() || !ex.audio.analysable) {
      flat();
      return;
    }
    let frame = requestAnimationFrame(function tick() {
      const levels = ex.audio.levels();
      for (let i = 0; i < BARS; i++) if (bars[i]) bars[i].style.transform = `scaleY(${Math.max(IDLE, levels[i])})`;
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  });

  const BTN = 'grid h-9 w-9 flex-none place-items-center rounded-full text-ink transition duration-150 hover:bg-neutral-soft disabled:opacity-40';
</script>

{#if playing}
  <section aria-label={t('explorer.mini.label')} transition:fly={{ y: 24, duration: ms(DUR.enter) }}
    class="relative flex flex-none items-center gap-3 overflow-hidden rounded-2xl card px-3 py-2">
    <div class="relative h-10 w-10 flex-none">
      <span aria-hidden="true" class="breathe absolute -inset-2 rounded-full opacity-60 blur-[14px]" class:running={!paused}
        style:background={color}></span>
      <span class="relative grid h-10 w-10 place-items-center overflow-hidden rounded-[10px] text-white"
        style:background={cover ? undefined : 'linear-gradient(135deg,#a78bfa,#6d28d9)'}>
        {#if cover}<img src={cover} alt="" draggable="false" class="h-full w-full object-cover" onerror={() => (missing = cover)} />
        {:else}<Icon name="music" size={18} />{/if}
      </span>
    </div>
    <b class="min-w-0 flex-1 truncate text-sm text-ink">{playing.title}</b>
    {#if ex.state.playError}
      <span role="alert" class="flex flex-none items-center gap-1.5 text-xs font-semibold text-bad">
        <Icon name="triangle-alert" size={14} />{t('explorer.mini.error')}
      </span>
    {/if}
    <div aria-hidden="true" class="flex h-6 flex-none items-end gap-[2px] {ex.state.playError ? 'hidden' : ''}">
      {#each Array.from({ length: BARS }, (_, i) => i) as i (i)}
        <span bind:this={bars[i]} class="h-full w-[3px] origin-bottom rounded-full bg-accent" style:transform="scaleY({IDLE})"></span>
      {/each}
    </div>
    <button type="button" class={BTN} onclick={() => ex.toggleTrack()} aria-label={t(paused ? 'explorer.preview.play' : 'explorer.preview.pause')}>
      <Icon name={paused ? 'play' : 'pause'} size={16} class={paused ? 'fill-current' : ''} />
    </button>
    <button type="button" class={BTN} disabled={!ex.nextTrack} onclick={() => ex.skipTrack()}
      aria-label={t('explorer.preview.next_track')} title={t('explorer.preview.next_track')}>
      <Icon name="skip-forward" size={16} />
    </button>
    <button type="button" class={BTN} onclick={() => ex.stopTrack()} aria-label={t('explorer.mini.stop')} title={t('explorer.mini.stop')}>
      <Icon name="x" size={16} />
    </button>
    <span aria-hidden="true" class="absolute right-0 bottom-0 left-0 h-[2px] origin-left bg-accent"
      style:transform="scaleX({progress})"></span>
  </section>
{/if}

<style>
  .breathe { animation: breathe 3.2s ease-in-out infinite paused; }
  .breathe.running { animation-play-state: running; }
  @keyframes breathe { 0%, 100% { transform: scale(.9); opacity: .3; } 50% { transform: scale(1.1); opacity: .65; } }
  @media (prefers-reduced-motion: reduce) { .breathe { animation: none; } }
</style>
