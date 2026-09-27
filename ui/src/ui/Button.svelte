<script lang="ts">
  import type { Snippet } from 'svelte';

  type Props = {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    disabled?: boolean;
    type?: 'button' | 'submit';
    pressed?: boolean;
    label?: string;
    title?: string;
    class?: string;
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
  };
  let { variant = 'secondary', size = 'md', disabled = false, type = 'button', pressed, label, title,
    class: cls = '', onclick, children }: Props = $props();
  const VARIANT = {
    primary: 'bg-accent text-white shadow-[0_6px_16px_-6px_var(--color-accent)] hover:brightness-110',
    secondary: 'border border-line bg-surface text-ink hover:bg-surface-2',
    ghost: 'text-mut hover:bg-surface-2 hover:text-ink',
    danger: 'bg-bad text-white hover:brightness-110',
  };
  const SIZE = {
    sm: 'rounded-lg px-2.5 py-1 text-[11.5px]',
    md: 'rounded-[10px] px-3.5 py-2',
    lg: 'rounded-xl px-4 py-2.5 text-[13px]',
  };
</script>

<button {type} {disabled} {title} aria-pressed={pressed} aria-label={label} {onclick}
  class="inline-flex items-center justify-center gap-1.5 font-semibold whitespace-nowrap transition duration-150
    disabled:cursor-default disabled:opacity-50 {VARIANT[variant]} {SIZE[size]} {cls}">
  {@render children()}
</button>
