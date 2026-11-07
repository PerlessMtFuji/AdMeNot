<script lang="ts">
  import { tick } from 'svelte';

  type Props = { checked: boolean; label: string; disabled?: boolean;
    onchange: (v: boolean) => Promise<boolean> | void };
  let { checked, label, disabled = false, onchange }: Props = $props();

  // Jednokierunkowe: po nieudanym zapisie (onchange → false) przełącznik wraca do zapisanej wartości.
  let shown = $state(false);
  $effect(() => { shown = checked; });

  async function toggle(): Promise<void> {
    const next = !shown;
    shown = next;
    const ok = await onchange(next);
    await tick();
    if (ok === false) shown = checked;
  }
</script>

<button type="button" role="switch" aria-checked={shown} aria-label={label} {disabled} onclick={toggle}
  class="relative h-[21px] w-9 flex-none cursor-pointer rounded-full transition-colors duration-150 disabled:cursor-default disabled:opacity-50
    {shown ? 'bg-accent' : 'bg-line'}">
  <span class="absolute top-[2.5px] h-4 w-4 rounded-full bg-white shadow-sm transition-[left] duration-150
    {shown ? 'left-[17.5px]' : 'left-[2.5px]'}"></span>
</button>
