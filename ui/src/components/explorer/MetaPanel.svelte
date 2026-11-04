<script lang="ts">
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { formatBytes } from '../../lib/explorer/logic';
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import type { EntryMeta, EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';

  /** Panel ⓘ: wszystkie pola z `explorer_meta` w grupach (zdjęcie/film/utwór, aparat, lokalizacja, plik). */
  type Props = { entry: EntryView; meta: EntryMeta | null; onmap: (lat: number, lon: number) => void };
  let { entry, meta, onmap }: Props = $props();

  type Row = [label: string, value: string];
  const SKIP = new Set(['gps', 'size', 'mtime', 'path', 'width', 'height']);
  const CAMERA = /^(Make|Model|Lens\w*|Software|BodySerialNumber)$/;
  const locale = $derived(i18n.lang === 'pl' ? 'pl-PL' : 'en-US');

  function humanize(key: string): string {
    return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ');
  }

  function label(key: string): string {
    const text = t(`explorer.preview.field.${key}`);
    return text.startsWith('explorer.preview.field.') ? humanize(key) : text;
  }

  function value(v: unknown): string {
    if (typeof v === 'number') return String(Math.round(v * 10_000) / 10_000);
    if (Array.isArray(v)) return v.map(value).join(' · ');
    if (v !== null && typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }

  const gps = $derived.by(() => {
    const g = meta?.gps as { lat?: unknown; lon?: unknown; alt?: unknown } | null | undefined;
    return typeof g?.lat === 'number' && typeof g.lon === 'number'
      ? { lat: Number(g.lat.toFixed(6)), lon: Number(g.lon.toFixed(6)), alt: typeof g.alt === 'number' ? g.alt : null }
      : null;
  });

  const groups = $derived.by(() => {
    const m = meta ?? ({} as Record<string, unknown>);
    const main: Row[] = [];
    const camera: Row[] = [];
    const place: Row[] = [];
    if (typeof m.width === 'number' && typeof m.height === 'number') {
      main.push([t('explorer.preview.meta.dimensions'), `${m.width} × ${m.height}`]);
    }
    for (const [key, v] of Object.entries(m)) {
      if (SKIP.has(key) || v === null || v === undefined) continue;
      const row: Row = [label(key), key === 'date_taken' && typeof v === 'number'
        ? new Date(v).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' }) : value(v)];
      (key.startsWith('GPS') ? place : CAMERA.test(key) ? camera : main).push(row);
    }
    const file: Row[] = [
      [t('explorer.preview.meta.name'), entry.label ?? entry.name],
      [t('explorer.preview.meta.path'), String(m.path ?? entry.path)],
      [t('explorer.preview.meta.size'), formatBytes(Number(m.size ?? entry.size), i18n.lang)],
      [t('explorer.preview.meta.modified'), new Date(Number(m.mtime ?? entry.mtime) * 1000)
        .toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' })],
    ];
    const mainTitle = t(`explorer.preview.meta.${entry.type === 'video' ? 'video' : entry.type === 'audio' ? 'audio' : 'photo'}`);
    return [[mainTitle, main], [t('explorer.preview.meta.camera'), camera], [t('explorer.preview.meta.location'), place],
      [t('explorer.preview.meta.file'), file]] as [string, Row[]][];
  });
</script>

<aside aria-label={t('explorer.preview.info')} transition:fly={{ x: 24, duration: ms(DUR.enter), easing: cubicOut }}
  class="w-[320px] flex-none overflow-y-auto border-l border-white/10 bg-black/40 p-5 text-sm text-white backdrop-blur-xl">
  {#each groups as [title, rows] (title)}
    {@const isPlace = title === t('explorer.preview.meta.location')}
    {#if rows.length || (isPlace && gps)}
      <section class="mb-5">
        <h3 class="mb-2 text-2xs font-extrabold tracking-wide text-white/55 uppercase">{title}</h3>
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
          {#if isPlace && gps}
            <dt class="text-white/60">{t('explorer.preview.meta.coords')}</dt>
            <dd class="font-semibold tabular-nums">{gps.lat}, {gps.lon}</dd>
          {/if}
          {#each rows as [k, v], i (i)}
            <dt class="text-white/60">{k}</dt>
            <dd class="min-w-0 break-words">{v}</dd>
          {/each}
        </dl>
        {#if isPlace && gps}
          <button type="button" onclick={() => onmap(gps.lat, gps.lon)}
            class="mt-3 inline-flex items-center gap-1.5 rounded-[10px] bg-white/10 px-3 py-1.5 font-semibold transition duration-150 hover:bg-white/20">
            <Icon name="map-pin" size={14} />{t('explorer.preview.meta.map')}
          </button>
        {/if}
      </section>
    {/if}
  {/each}
</aside>
