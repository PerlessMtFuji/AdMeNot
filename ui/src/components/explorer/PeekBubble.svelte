<script lang="ts">
  import { untrack } from 'svelte';
  import { cubicOut } from 'svelte/easing';
  import { scale } from 'svelte/transition';
  import { AudioPlayer } from '../../lib/explorer/audio';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { MusicHold } from '../../lib/explorer/musichold';
  import { closePdfWorker } from '../../lib/explorer/pdf';
  import { peekKind, peekSize, PeekTimer, placeBubble, type PeekKind } from '../../lib/explorer/peek';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { DUR, ms } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import PeekContent from './PeekContent.svelte';

  /** Dymek podglądu przy pliku pod kursorem. Nie łapie myszy i nie ma przycisków; błąd pliku po prostu go zamyka. */
  let { ex, thumbs }: { ex: ExplorerController; thumbs: ThumbQueue } = $props();
  const s = untrack(() => ex.state);
  /** Tyle ciszy po kółku lub przewijaniu, zanim plik pod kursorem znów może dostać dymek. */
  const QUIET_MS = 120;

  type Open = { entry: EntryView; kind: PeekKind; x: number; y: number; w: number; h: number };
  /** Migawka z chwili otwarcia: odświeżenie folderu nie zaczyna odtwarzania od nowa. */
  let open = $state.raw<Open | null>(null);
  let pointerType = $state('mouse');
  let pressed = $state(false);
  let dragging = $state(false);
  let scrolling = $state(false);
  let quiet: ReturnType<typeof setTimeout> | undefined;

  const timer = new PeekTimer(show, hide);

  // Odtwarzacz muzyki powstaje przy pierwszym utworze, więc dymek sięga po niego tylko, gdy coś jest załadowane.
  const hold = new MusicHold({
    get paused() { return s.playing ? ex.audio.el.paused : true; },
    get source() { return s.playing ? ex.audio.el.getAttribute('src') : null; },
    pause: () => ex.audio.pause(),
    play: () => { void ex.audio.play().catch(() => {}); },
  });
  const take = () => untrack(() => hold.take());

  let own: AudioPlayer | null = null;
  const player = () => (own ??= new AudioPlayer());

  /** Plik pod kursorem, o ile dymek ma mu co pokazać; reszta (folder, HEIC) liczy się jak „poza plikami”. */
  const target = $derived.by(() => {
    if (pointerType !== 'mouse' || s.hover === null) return null;
    const entry = s.byPath.get(s.hover);
    return entry && peekKind(entry) ? entry.path : null;
  });
  /** Wszystkie powody wstrzymania w jednej wartości: `hold` dostaje tylko zmiany. */
  const held = $derived(!s.peek || s.offline || s.preview !== null || s.problems !== null || s.leaveAsk > 0 || s.drop !== null
    || pressed || dragging || scrolling);

  function show(path: string): void {
    const entry = s.byPath.get(path);
    const kind = entry ? peekKind(entry) : null;
    const tile = document.querySelector(`[data-path="${CSS.escape(path)}"]`);
    if (!entry || !kind || !tile) {
      timer.dismiss();
      return;
    }
    const size = peekSize(kind);
    const at = placeBubble(tile.getBoundingClientRect(), size, { w: window.innerWidth, h: window.innerHeight });
    open = { entry, kind, ...at, ...size };
  }

  function hide(): void {
    open = null;
    hold.release();
  }

  const close = () => timer.dismiss();

  $effect(() => {
    const path = target;
    untrack(() => timer.hover(path));
  });
  $effect(() => {
    const on = held;
    untrack(() => timer.hold(on));
  });
  $effect(() => {
    void s.path;
    untrack(close);
  });
  $effect(() => {
    if (open && !s.byPath.has(open.entry.path)) untrack(close);
  });
  // Pełny podgląd przejmuje dźwięk: muzyka w tle nie może wrócić mu w poprzek.
  $effect(() => {
    if (s.preview !== null) untrack(() => hold.forget());
  });

  function scrolled(): void {
    scrolling = true;
    clearTimeout(quiet);
    quiet = setTimeout(() => (scrolling = false), QUIET_MS);
  }

  $effect(() => {
    const stop = new AbortController();
    const early = { capture: true, signal: stop.signal };
    const light = { ...early, passive: true };
    const seen = (e: PointerEvent) => { pointerType = e.pointerType; };
    const released = () => { pressed = false; dragging = false; };
    window.addEventListener('pointerdown', seen, light);
    window.addEventListener('pointermove', seen, light);
    window.addEventListener('mousedown', () => { close(); pressed = true; }, early);
    window.addEventListener('mouseup', released, early);
    window.addEventListener('keydown', close, early);
    window.addEventListener('dragstart', () => { close(); dragging = true; }, early);
    window.addEventListener('dragend', released, early);
    window.addEventListener('drop', released, early);
    window.addEventListener('wheel', scrolled, light);
    window.addEventListener('scroll', scrolled, light);
    // Bez fazy przechwytywania: tu trafia tylko blur okna, a nie każdego pola, i tylko wyjście z całej strony.
    window.addEventListener('blur', () => { close(); released(); }, { signal: stop.signal });
    document.documentElement.addEventListener('mouseleave', close, { signal: stop.signal });
    return () => stop.abort();
  });

  $effect(() => () => {
    clearTimeout(quiet);
    timer.destroy();
    hold.forget();
    own?.dispose();
    closePdfWorker();
  });

  // Dymek żyje w <body> (jak Preview): przodek z transformacją nie zamknie `position: fixed` w swojej kolumnie.
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
</script>

{#if open}
  <div use:portal data-testid="peek" aria-hidden="true" in:scale={{ start: 0.96, duration: ms(DUR.micro), easing: cubicOut }}
    class="card pointer-events-none fixed z-30 overflow-hidden rounded-2xl"
    style:left="{open.x}px" style:top="{open.y}px" style:width="{open.w}px" style:height="{open.h}px">
    {#key open.entry.path}
      <PeekContent {ex} {thumbs} entry={open.entry} kind={open.kind} audio={player} ontake={take} onfail={close} />
    {/key}
  </div>
{/if}
