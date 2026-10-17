<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Card from '../ui/Card.svelte';
  import Progress from '../ui/Progress.svelte';
  import ApkEstimate from './ApkEstimate.svelte';

  // Analiza APK w tle. hero: na razie nic nie oznaczono, więc zamiast przedwczesnego „czysto”
  // stan „w toku” z pierścieniem; inaczej karta z paskiem nad listą aplikacji.
  let { hero = false }: { hero?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const value = $derived(s.apk.total ? s.apk.done / s.apk.total : 0);
  const pct = $derived(Math.round(Math.min(1, Math.max(0, value)) * 100));
  const label = $derived(t('summary.apk_running', { done: s.apk.done, total: s.apk.total }));
  const R = 34;
  const C = 2 * Math.PI * R;
</script>

{#if hero}
  <div class="grid place-items-center gap-2 py-10 text-center">
    <span class="relative grid h-20 w-20 place-items-center rounded-full bg-neutral-soft shadow-[0_0_0_12px_var(--color-accent-soft)]"
      role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}>
      <svg class="absolute inset-0 -rotate-90" viewBox="0 0 80 80" aria-hidden="true">
        <circle cx="40" cy="40" r={R} fill="none" stroke="var(--color-line)" stroke-width="6" />
        <circle cx="40" cy="40" r={R} fill="none" stroke="var(--color-accent)" stroke-width="6" stroke-linecap="round"
          stroke-dasharray={C} stroke-dashoffset={C * (1 - value)} class="transition-[stroke-dashoffset] duration-500" />
      </svg>
      <b class="mono relative text-sm text-ink">{pct}%</b>
    </span>
    <p class="mt-3 text-mut">{t('results.apk_sub')}</p>
    <p class="mono text-xs text-soft">{label}</p>
    <ApkEstimate class="max-w-[52ch] text-xs" />
  </div>
{:else}
  <Card class="px-4 py-3">
    <div class="flex items-center gap-3 text-sm">
      <span class="spin flex-none"></span>
      <span class="font-semibold whitespace-nowrap text-ink">{label}</span>
      <div class="min-w-24 flex-1"><Progress {value} {label} /></div>
    </div>
    <ApkEstimate class="mt-1.5 pl-6 text-xs" />
  </Card>
{/if}
