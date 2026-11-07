<script lang="ts">
  import type { Rect } from '../../lib/explorer/virtual';

  let { rect }: { rect: Rect } = $props();
</script>

<!-- Prostokąt zaznaczania: zwykła ramka w kolorze akcentu (bez „maszerujących mrówek”). -->
<div data-testid="lasso" aria-hidden="true"
  class="pointer-events-none absolute z-20 rounded-[6px] border border-accent bg-[color-mix(in_srgb,var(--color-accent)_12%,transparent)]"
  style:left="{rect.x}px" style:top="{rect.y}px" style:width="{rect.w}px" style:height="{rect.h}px"></div>
