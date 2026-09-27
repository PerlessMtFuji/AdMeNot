<script lang="ts">
  import type { Snippet } from 'svelte';

  // Ikona z APK (data URI bitmapy — backend sprawdza nagłówek pliku); bez niej albo gdy się nie
  // wczyta, zostaje awatar z inicjałem przekazany jako children.
  type Props = { icon: string | null | undefined; class?: string; children: Snippet };
  let { icon, class: size = '', children }: Props = $props();
  let broken = $state<string | null>(null);
</script>

{#if icon && broken !== icon}
  <img src={icon} alt="" aria-hidden="true" draggable="false" data-app-icon
    class="flex-none rounded-[22%] object-contain drop-shadow-[0_2px_4px_rgb(0_0_0/.18)] {size}"
    onerror={() => (broken = icon ?? null)} />
{:else}
  {@render children()}
{/if}
