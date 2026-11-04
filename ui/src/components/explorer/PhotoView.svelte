<script lang="ts">
  import { fade } from 'svelte/transition';
  import { DUR, ms } from '../../lib/motion';
  import { t } from '../../lib/i18n/index.svelte';
  import type { EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';

  /** Zdjęcie w podglądzie: rozmyta poświata z tego samego obrazu, kółko = zoom do kursora, przeciąganie =
   *  przesuwanie, ⟳ obrót. Do czasu pobrania pliku widać miniaturę. */
  let { entry, onfail }: { entry: EntryView; onfail: () => void } = $props();

  const MAX_ZOOM = 8;
  const STEP = 1.25;
  let zoom = $state(1);
  let x = $state(0);
  let y = $state(0);
  let turn = $state(0);  // kolejne obroty o 90°
  let loaded = $state(false);
  let dragging = $state(false);
  let box = $state({ w: 0, h: 0 });
  let natural = $state({ w: 0, h: 0 });
  let stage = $state<HTMLElement>();

  // Rozmiar okna zdjęcia (do dopasowania po obrocie); w testach bez ResizeObserver zostaje 0 i obrót tylko obraca.
  $effect(() => {
    const el = stage;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const watch = new ResizeObserver(() => { box = { w: el.clientWidth, h: el.clientHeight }; });
    watch.observe(el);
    return () => watch.disconnect();
  });

  // Obrócone o 90° zdjęcie ma zamienione boki: zmniejszamy je, żeby nadal mieściło się w oknie.
  const fit = $derived.by(() => {
    if (turn % 2 === 0 || !natural.w || !box.w) return 1;
    const c = Math.min(box.w / natural.w, box.h / natural.h);
    return Math.min(1, box.w / (c * natural.h), box.h / (c * natural.w));
  });
  const transform = $derived(`translate(${x}px, ${y}px) rotate(${turn * 90}deg) scale(${zoom * fit})`);
  const src = $derived(entry.thumb ?? entry.url ?? '');

  function measure(e: Event): void {
    const img = e.currentTarget as HTMLImageElement;
    natural = { w: img.naturalWidth, h: img.naturalHeight };
  }

  function wheel(e: WheelEvent): void {
    e.preventDefault();
    const next = Math.min(MAX_ZOOM, Math.max(1, zoom * (e.deltaY < 0 ? STEP : 1 / STEP)));
    if (next === zoom) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    // punkt pod kursorem zostaje pod kursorem: przesunięcie skaluje się razem z powiększeniem
    const cx = e.clientX - (r.left + r.width / 2);
    const cy = e.clientY - (r.top + r.height / 2);
    const k = next / zoom;
    x = next === 1 ? 0 : cx - (cx - x) * k;
    y = next === 1 ? 0 : cy - (cy - y) * k;
    zoom = next;
  }

  let drag: { px: number; py: number; x: number; y: number } | null = null;
  function down(e: PointerEvent): void {
    if (e.button !== 0 || zoom === 1) return;
    drag = { px: e.clientX, py: e.clientY, x, y };
    dragging = true;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  }
  function move(e: PointerEvent): void {
    if (!drag) return;
    x = drag.x + e.clientX - drag.px;
    y = drag.y + e.clientY - drag.py;
  }
  function up(): void {
    drag = null;
    dragging = false;
  }
  function rotate(): void {
    turn += 1;
    x = 0;
    y = 0;
  }
</script>

<div class="absolute inset-0 overflow-hidden" aria-hidden="true">
  <img src={src} alt="" class="glow pointer-events-none absolute inset-0 h-full w-full scale-125 object-cover opacity-70" />
</div>
<div class="absolute inset-0 touch-none overflow-hidden {zoom > 1 ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : ''}"
  bind:this={stage}
  role="presentation" onwheel={wheel} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}>
  <div data-morph="photo" class="absolute inset-0 {dragging ? '' : 'transition-transform duration-150 ease-out motion-reduce:transition-none'}"
    style:transform={transform}>
    <img src={entry.thumb ?? ''} alt="" draggable="false" class="absolute inset-0 h-full w-full object-contain select-none"
      onload={measure} />
    {#if entry.url}
      <img src={entry.url} alt={entry.label ?? entry.name} draggable="false" onload={(e) => { loaded = true; measure(e); }} onerror={onfail}
        class="absolute inset-0 h-full w-full object-contain select-none transition-opacity duration-300 {loaded ? 'opacity-100' : 'opacity-0'}" />
    {/if}
  </div>
</div>
{#if !loaded}
  <span class="spin absolute top-1/2 left-1/2" role="status" aria-label={t('explorer.preview.loading')}
    out:fade={{ duration: ms(DUR.micro) }}></span>
{/if}
<button type="button" onclick={rotate} aria-label={t('explorer.preview.rotate')} title={t('explorer.preview.rotate')}
  class="absolute right-4 bottom-4 grid h-10 w-10 place-items-center rounded-full bg-black/45 text-white backdrop-blur-md
    transition duration-150 hover:bg-black/65">
  <Icon name="rotate-cw" size={18} />
</button>

<style>
  .glow { filter: blur(40px) saturate(1.4); animation: drift 24s ease-in-out infinite alternate; }
  @keyframes drift { from { transform: scale(1.25) translate(-2%, -1%); } to { transform: scale(1.35) translate(2%, 1.5%); } }
  @media (prefers-reduced-motion: reduce) { .glow { animation: none; } }
</style>
