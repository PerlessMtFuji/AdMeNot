<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import Button from '../../ui/Button.svelte';

  type Props = { value: string | null; placeholder: string; pick: () => Promise<string | null>;
    onchange: (v: string | null) => void; clearable?: boolean };
  let { value, placeholder, pick, onchange, clearable = false }: Props = $props();

  async function change(): Promise<void> {
    const chosen = await pick();
    if (chosen !== null) onchange(chosen);
  }
</script>

<span title={value ?? placeholder} data-path
  class="max-w-[260px] truncate rounded-[9px] border border-line bg-surface-2 px-[9px] py-[5px] font-mono text-[11.5px]
    {value ? 'text-mut' : 'text-soft'}">{value ?? placeholder}</span>
<Button size="sm" onclick={change}>{t('settings.change')}</Button>
{#if clearable && value}
  <Button size="sm" variant="ghost" onclick={() => onchange(null)}>{t('settings.default')}</Button>
{/if}
