<script lang="ts">
  import { cubicOut } from 'svelte/easing';
  import { Tween } from 'svelte/motion';
  import { DUR, ms } from '../lib/motion';

  let { value }: { value: number } = $props();
  const tween = new Tween(0, { easing: cubicOut });
  $effect(() => {
    void tween.set(value, { duration: ms(DUR.count) });
  });
</script>

<span class="tabular-nums">{Math.round(tween.current)}</span>
