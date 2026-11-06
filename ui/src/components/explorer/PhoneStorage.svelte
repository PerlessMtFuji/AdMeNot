<script lang="ts">
  import { formatBytes } from '../../lib/explorer/logic';
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import type { StorageView } from '../../lib/types';

  /** Sylwetka telefonu z falującą „cieczą”: poziom = zajęte / całość, rośnie na żywo przy wgrywaniu. */
  let { usage }: { usage: StorageView | null } = $props();

  // Wnętrze ekranu sylwetki (jednostki viewBox) — ciecz przesuwa się w nim samym `transform`.
  const TOP = 14;
  const HEIGHT = 84;
  const GROUPS = [['photos', '#2563eb'], ['videos', '#e11d48'], ['whatsapp', '#059669'], ['other', '#8b93a7']] as const;

  const fraction = $derived(usage && usage.total > 0 ? Math.min(1, Math.max(0, usage.used / usage.total)) : 0);
  const percent = $derived(Math.round(fraction * 100));
  const rise = $derived(HEIGHT * (1 - fraction));
  const size = (bytes: number) => formatBytes(bytes, i18n.lang);
  const share = (bytes: number) => (usage && usage.used > 0 ? (100 * bytes) / usage.used : 0);
</script>

<section aria-label={t('explorer.storage.label')} class="flex flex-col items-center gap-2 border-t border-line/70 pt-3">
  <div class="lbl self-start px-2">{t('explorer.storage.label')}</div>
  <div class="relative">
    <svg viewBox="0 0 60 112" width="72" height="134" role="img" aria-label={t('explorer.storage.level', { percent })}
      data-testid="phone-storage">
      <defs>
        <clipPath id="phone-screen"><rect x="6" y={TOP} width="48" height={HEIGHT} rx="5" /></clipPath>
      </defs>
      <rect x="1.5" y="1.5" width="57" height="109" rx="11" fill="#1f2937" stroke="var(--color-line)" stroke-width="1" />
      <rect x="6" y={TOP} width="48" height={HEIGHT} rx="5" fill="var(--color-surface-2)" />
      <g clip-path="url(#phone-screen)">
        <g class="liquid" style="transform:translateY({TOP + rise}px)" data-level={percent}>
          <g class="wave wave-back"><path d="M0 2 q5 -4 10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 V100 H0Z" fill="var(--color-accent)" opacity=".35" /></g>
          <g class="wave"><path d="M0 3 q5 -4 10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 t10 0 V100 H0Z" fill="var(--color-accent)" opacity=".85" /></g>
        </g>
      </g>
      <rect x="22" y="5" width="16" height="3" rx="1.5" fill="#374151" />
    </svg>
    <span class="pointer-events-none absolute inset-x-0 top-[58%] -translate-y-1/2 text-center text-md font-extrabold text-white tabular-nums drop-shadow">
      {#if usage}{percent}%{/if}
    </span>
  </div>
  {#if usage}
    <div class="text-center text-2xs font-semibold text-mut tabular-nums">
      {t('explorer.storage.used_of', { used: size(usage.used), total: size(usage.total) })}
      <br />{t('explorer.storage.free', { size: size(usage.free) })}
    </div>
    <div class="flex h-1.5 w-full overflow-hidden rounded-full bg-neutral-soft" aria-hidden="true">
      {#each GROUPS as [key, color] (key)}
        <span style="width:{share(usage.groups[key])}%;background:{color}"></span>
      {/each}
    </div>
    <ul class="flex w-full flex-col gap-0.5 px-1">
      {#each GROUPS as [key, color] (key)}
        <li class="flex items-center gap-1.5 text-2xs text-mut">
          <span class="h-2 w-2 flex-none rounded-full" style="background:{color}"></span>
          <span class="min-w-0 flex-1 truncate">{t(`explorer.storage.group.${key}`)}</span>
          <span class="flex-none font-semibold tabular-nums text-ink">{size(usage.groups[key])}</span>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  /* Poziom: płynny `transform` (zmiana na żywo przy wgrywaniu); fala: przesunięcie o okres wzoru. */
  .liquid { transition: transform 500ms cubic-bezier(.2, .8, .2, 1); }
  .wave { animation: storage-wave 2.4s linear infinite; }
  .wave-back { animation-duration: 3.6s; animation-direction: reverse; }
  @keyframes storage-wave { from { transform: translateX(0); } to { transform: translateX(-20px); } }
</style>
