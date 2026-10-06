<script lang="ts">
  import type { Snippet } from 'svelte';

  type Props = {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg' | 'icon';
    disabled?: boolean;
    type?: 'button' | 'submit';
    pressed?: boolean;
    label?: string;
    title?: string;
    describedby?: string;
    class?: string;
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
  };
  let { variant = 'secondary', size = 'md', disabled = false, type = 'button', pressed, label, title,
    describedby, class: cls = '', onclick, children }: Props = $props();
  const VARIANT = {
    primary: 'btn-primary text-white',
    secondary: 'btn-secondary text-ink',
    ghost: 'text-mut hover:bg-neutral-soft hover:text-ink',
    danger: 'btn-danger text-white',
  };
  const SIZE = {
    sm: 'rounded-[10px] px-3 py-1.5 text-sm',
    md: 'rounded-xl px-4 py-2.5',
    lg: 'rounded-[14px] px-5 py-3 text-md',
    icon: 'aspect-square h-[calc(1.25rem+var(--text-base)*1.5)] rounded-xl p-0', // wysokość jak md (py-2.5 + linia tekstu); sam symbol, nazwę niesie aria-label i podpowiedź
  };
</script>

<button {type} {disabled} {title} aria-pressed={pressed} aria-label={label} aria-describedby={describedby} {onclick}
  class="inline-flex items-center justify-center gap-1.5 font-semibold whitespace-nowrap transition duration-150
    enabled:active:translate-y-px disabled:cursor-default disabled:opacity-50 {VARIANT[variant]} {SIZE[size]} {cls}">
  {@render children()}
</button>
