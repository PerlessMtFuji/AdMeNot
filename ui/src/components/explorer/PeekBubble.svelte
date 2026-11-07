<script lang="ts">
  import { untrack } from 'svelte';
  import { cubicOut } from 'svelte/easing';
  import { scale } from 'svelte/transition';
  import { AudioPlayer } from '../../lib/explorer/audio';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { MusicHold } from '../../lib/explorer/musichold';
  import { closePdfWorker } from '../../lib/explorer/pdf';
  import { fitBubble, peekKind, peekSize, PeekTimer, placeBubble, type PeekKind, type PeekRect } from '../../lib/explorer/peek';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import { DUR, ms } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import PeekContent from './PeekContent.svelte';

  /** Dymek podglądu przy pliku pod kursorem. Nie łapie myszy i nie ma przycisków; błąd pliku po prostu go zamyka. */
  let { ex, thumbs }: { ex: ExplorerController; thumbs: ThumbQueue } = $props();
  const s = untrack(() => ex.state);
  /** Tyle ciszy po kółku lub przewijaniu, zanim plik pod kursorem znów może dostać dymek. */
  const QUIET_MS = 120;

  type Open = { entry: EntryView; kind: PeekKind; sweep: boolean; tile: Element; anchor: PeekRect; x: number; y: number; w: number; h: number };
  /** Migawka z chwili otwarcia: odświeżenie folderu nie zaczyna odtwarzania od nowa. */
  let open = $state.raw<Open | null>(null);
  const showing = $derived(open !== null);
  let pointerType = $state('mouse');
  /** Ostatnia pozycja kursora w poziomie: na liście to przy niej stoi dymek. */
  let mouseX = 0;
  let pressed = $state(false);
  let dragging = $state(false);
  let scrolling = $state(false);
  /** Okno w tle nie gra: `hasFocus` bywa nieaktualne (pod CDP zostało `true`), więc dalej prowadzą je zdarzenia okna. */
  let focused = $state(document.hasFocus());
  let quiet: ReturnType<typeof setTimeout> | undefined;

  const timer = new PeekTimer(show, hide);

  // Odtwarzacz muzyki powstaje przy pierwszym utworze, więc dymek sięga po niego tylko, gdy coś jest załadowane.
  const hold = new MusicHold({
    get paused() { return s.playing ? ex.audio.el.paused : true; },
    get source() { return s.playing ? ex.audio.el.getAttribute('src') : null; },
    pause: () => ex.audio.pause(),
    play: () => { void ex.audio.play().catch(() => {}); },
  });
  const take = () => hold.take();

  let own: AudioPlayer | null = null;
  const player = () => (own ??= new AudioPlayer());

  /** Plik pod kursorem, o ile dymek ma mu co pokazać; reszta (folder, HEIC) liczy się jak „poza plikami”.
   *  Utwór z mini-odtwarzacza też: dymek przerwałby to, czego serwisant właśnie słucha. */
  const target = $derived.by(() => {
    if (pointerType !== 'mouse' || s.hover === null) return null;
    const entry = s.byPath.get(s.hover);
    return entry && peekKind(entry) && entry.path !== s.playing?.path ? entry.path : null;
  });
  /** Wszystkie powody wstrzymania w jednej wartości: `hold` dostaje tylko zmiany. */
  const held = $derived(!s.peek || s.offline || s.preview !== null || s.problems !== null || s.leaveAsk > 0 || s.drop !== null
    || pressed || dragging || scrolling || !focused);

  function show(path: string, sweep: boolean): void {
    if (open?.entry.path === path) return;  // powrót w przejeździe: to, co gra lub się rysuje, zostaje
    const entry = s.byPath.get(path);
    const kind = entry ? peekKind(entry) : null;
    const tile = document.querySelector(`[data-path="${CSS.escape(path)}"]`);
    if (!entry || !kind || !tile) {
      timer.dismiss();
      return;
    }
    const size = peekSize(kind);
    const box = tile.getBoundingClientRect();
    // Wiersz listy ma całą szerokość okna plików: obok niego nie ma miejsca, więc dymek staje obok kursora.
    const anchor = s.view === 'list' ? { left: mouseX, right: mouseX, top: box.top, bottom: box.bottom } : box;
    const at = placeBubble(anchor, size, { w: window.innerWidth, h: window.innerHeight });
    open = { entry, kind, sweep, tile, anchor, ...at, ...size };
  }

  /** Znane proporcje zdjęcia lub filmu: dymek przyjmuje ich kształt, tylko gdy to widać (miniatura i plik różnią się
   *  o zaokrąglenie). */
  function fit(w: number, h: number): void {
    if (!open || !w || !h) return;
    const win = { w: window.innerWidth, h: window.innerHeight };
    const size = fitBubble(w / h, win);
    if (Math.abs(size.w - open.w) < 3 && Math.abs(size.h - open.h) < 3) return;
    open = { ...open, ...size, ...placeBubble(open.anchor, size, win) };
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
  // Kafle są wirtualizowane: plik pod kursorem może zniknąć z DOM bez żadnego zdarzenia myszy.
  $effect(() => {
    const tile = open?.tile;
    if (!tile?.parentNode) return;
    const watch = new MutationObserver(() => { if (!tile.isConnected) close(); });
    watch.observe(tile.parentNode, { childList: true });
    return () => watch.disconnect();
  });
  // Pełne zdjęcie z dymka czeka za miniaturami na zapas nawet kilka razy dłużej (pomiar: 361 ms zamiast 55 ms).
  $effect(() => {
    const on = showing;
    untrack(() => thumbs.pauseSpare(on));
  });
  // Pełny podgląd przejmuje dźwięk, a po odłączeniu telefonu strumień jest martwy: wznowienie skończyłoby się błędem.
  $effect(() => {
    if (s.preview !== null || s.offline) untrack(() => hold.forget());
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
    const seen = (e: PointerEvent) => { pointerType = e.pointerType; mouseX = e.clientX; };
    const released = () => { pressed = false; dragging = false; };
    window.addEventListener('pointerdown', seen, light);
    window.addEventListener('pointermove', seen, light);
    // Naciśnięcie w stronie to dowód fokusu, gdyby okno nie zgłosiło `focus`.
    window.addEventListener('mousedown', () => { close(); pressed = true; focused = true; }, early);
    window.addEventListener('mouseup', released, early);
    window.addEventListener('keydown', close, early);
    window.addEventListener('dragstart', () => { close(); dragging = true; }, early);
    window.addEventListener('dragend', released, early);
    window.addEventListener('drop', released, early);
    window.addEventListener('wheel', scrolled, light);
    window.addEventListener('scroll', scrolled, light);
    // Bez fazy przechwytywania: tu trafia tylko blur okna, a nie każdego pola, i tylko wyjście z całej strony.
    window.addEventListener('blur', () => { close(); released(); focused = false; }, { signal: stop.signal });
    window.addEventListener('focus', () => { focused = true; }, { signal: stop.signal });
    document.documentElement.addEventListener('mouseleave', close, { signal: stop.signal });
    return () => stop.abort();
  });

  $effect(() => () => {
    clearTimeout(quiet);
    timer.destroy();
    hold.forget();
    thumbs.pauseSpare(false);
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
      <PeekContent {ex} {thumbs} entry={open.entry} kind={open.kind} sweep={open.sweep} audio={player} ontake={take} onsize={fit} onfail={close} />
    {/key}
  </div>
{/if}
