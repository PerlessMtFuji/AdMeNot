<script lang="ts">
  import { untrack } from 'svelte';
  import { clock } from '../../lib/explorer/logic';
  import type { Thumb } from '../../lib/explorer/thumbs';
  import { reducedMotion } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon, { mediaGradient } from './FileIcon.svelte';

  type Props = {
    entry: EntryView;
    thumb: Thumb | null;
    /** Miniatury nie będzie (brak źródła, HEIC, film bez kodeka) — ikona typu. */
    noThumb: boolean;
    selected: boolean;
    /** Kaskada przy pierwszym pokazaniu folderu: chwila (`performance.now()`), w której kafel ma się wyostrzyć. */
    cascadeAt: number | null;
    /** Obrazu nie da się zdekodować — kafel przechodzi na ikonę typu. */
    onbroken: () => void;
  };
  let { entry, thumb, noThumb, selected, cascadeAt, onbroken }: Props = $props();

  // Miniatura już w pamięci przy pojawieniu się kafla (przewinięcie z powrotem) — bez efektu, od razu.
  const cachedAtMount = untrack(() => thumb !== null);
  const motion = !reducedMotion();
  const animate = $derived(motion && thumb !== null && (cascadeAt !== null || !cachedAtMount));
  const delay = $derived(thumb && cascadeAt !== null ? Math.max(0, Math.round(cascadeAt - performance.now())) : 0);
  const tint = $derived(thumb?.color || mediaGradient(entry.type));
  const glow = $derived(thumb?.color || 'var(--glow-accent)');
</script>

<!-- Zaznaczony kafel kurczy się lekko w ramce akcentu, z poświatą w kolorze zdjęcia. -->
<div class="relative h-full w-full overflow-hidden rounded-[12px] transition-transform duration-200 ease-[cubic-bezier(.2,.8,.2,1)]
  {selected ? 'scale-[.92]' : ''} {noThumb ? 'bg-surface-2 shadow-[var(--shadow-well)]' : ''}"
  style:background={noThumb ? undefined : tint}
  style:box-shadow={selected ? `0 0 0 2.5px var(--color-accent), 0 0 24px -2px ${glow}` : undefined}>
  {#if thumb && !noThumb}
    <img src={thumb.src} alt="" draggable="false" onerror={onbroken} class="absolute inset-0 h-full w-full object-cover {animate ? 'sharpen' : ''}"
      style:animation-delay={animate ? `${delay}ms` : undefined} />
  {:else if noThumb}
    <div class="absolute inset-0 flex flex-col items-center justify-center gap-1.5 px-2 pt-1">
      <FileIcon kind={entry.kind} type={entry.type} ext={entry.ext} locked={entry.locked} size={40} />
      <span class="w-full truncate text-center text-2xs font-semibold text-ink">{entry.label ?? entry.name}</span>
    </div>
  {/if}
  {#if (entry.type === 'video' || entry.type === 'audio') && !noThumb}
    <span class="absolute inset-0 grid place-items-center text-white">
      <span class="grid h-9 w-9 place-items-center rounded-full bg-black/35 shadow-[inset_0_0_0_1px_rgb(255_255_255/.35)] backdrop-blur-sm">
        <Icon name={entry.type === 'audio' ? 'music' : 'play'} size={16} strokeWidth={2.6}
          class={entry.type === 'audio' ? '' : 'translate-x-px fill-current'} />
      </span>
    </span>
    {#if thumb?.duration && Number.isFinite(thumb.duration)}
      <span class="absolute bottom-1.5 left-2 text-2xs font-bold text-white tabular-nums [text-shadow:0_1px_2px_rgb(0_0_0/.6)]">
        {clock(thumb.duration)}
      </span>
    {/if}
  {/if}
</div>
<!-- Kółko zaznaczenia: przy najechaniu (pusty), po zaznaczeniu — wypełnione akcentem. -->
<span data-check aria-hidden="true" class="absolute top-1.5 right-1.5 grid h-5 w-5 place-items-center rounded-full
  transition-[transform,opacity] duration-200 ease-[cubic-bezier(.2,1.6,.4,1)]
  {selected ? 'scale-100 bg-accent text-white opacity-100 shadow-[0_0_0_2px_var(--color-surface)]'
    : 'scale-90 bg-black/20 text-transparent opacity-0 shadow-[inset_0_0_0_1.5px_rgb(255_255_255/.9)] group-hover:opacity-100'}">
  <Icon name="check" size={12} strokeWidth={3.2} />
</span>
