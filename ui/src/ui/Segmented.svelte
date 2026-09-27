<script lang="ts" generics="T extends string">
  type Option = { value: T; label: string; tone?: 'bad' | 'warn' | 'accent' | 'ink' };
  type Props = { options: Option[]; value: T | null; label: string; size?: 'sm' | 'md'; disabled?: boolean;
    stretch?: boolean; onchange: (value: T) => void };
  let { options, value, label, size = 'md', disabled = false, stretch = false, onchange }: Props = $props();
  const TONE = { bad: 'text-bad', warn: 'text-warn', accent: 'text-accent', ink: 'text-ink' };
</script>

<div role="group" aria-label={label}
  class="{stretch ? 'flex' : 'inline-flex'} gap-0.5 rounded-xl bg-neutral-soft p-[3px] shadow-[var(--shadow-well)]">
  {#each options as o (o.value)}
    {@const on = o.value === value}
    <button type="button" aria-pressed={on} {disabled} onclick={() => onchange(o.value)}
      class="flex-1 rounded-[9px] font-semibold whitespace-nowrap transition duration-150 disabled:opacity-50
        {size === 'sm' ? 'px-2.5 py-1 text-sm' : 'px-3.5 py-1.5 text-sm'}
        {on ? `card ${TONE[o.tone ?? 'ink']}` : 'text-mut hover:text-ink'}">{o.label}</button>
  {/each}
</div>
