<script lang="ts" module>
  import type { FileKind } from '../../lib/types';

  // Kolor etykiety typu na „kartce” (spec §5.6, efekt 5) — jak barwy programów, które te pliki otwierają.
  const EXT_COLORS: [string, string[]][] = [
    ['#dc2626', ['pdf']],
    ['#2563eb', ['doc', 'docx', 'odt', 'rtf']],
    ['#16a34a', ['xls', 'xlsx', 'ods', 'csv']],
    ['#ea580c', ['ppt', 'pptx', 'odp']],
    ['#7c3aed', ['json', 'xml', 'html', 'htm', 'yml', 'yaml', 'ini', 'cfg', 'conf']],
    ['#0891b2', ['vcf', 'srt', 'epub', 'md']],
    ['#b45309', ['zip', 'rar', '7z', 'tar', 'gz']],
    ['#0f766e', ['apk', 'apks', 'xapk']],
  ];
  // Kafle mediów: gradient i symbol (miniatury zdjęć dochodzą w galerii — Task 11).
  const MEDIA = {
    image: { glyph: 'image', from: '#60a5fa', to: '#4f46e5' },
    video: { glyph: 'film', from: '#f472b6', to: '#be185d' },
    audio: { glyph: 'music', from: '#a78bfa', to: '#6d28d9' },
  } as const;

  export function extColor(ext: string): string {
    return EXT_COLORS.find(([, exts]) => exts.includes(ext))?.[0] ?? '#64748b';
  }

  export function isMedia(type: FileKind): type is keyof typeof MEDIA {
    return type in MEDIA;
  }
</script>

<script lang="ts">
  import Icon from '../../ui/Icon.svelte';

  type Props = { kind: 'dir' | 'file'; type: FileKind; ext: string; locked?: boolean; size?: number };
  let { kind, type, ext, locked = false, size = 30 }: Props = $props();
  const height = $derived(Math.round(size * 1.2));
  const label = $derived(ext.slice(0, 4).toUpperCase() || '•••');
  // Czteroznakowa etykieta (DOCX, XLSX) mniejszym pismem, żeby zmieściła się na małej kartce listy.
  const font = $derived(label.length > 3 ? Math.max(6.5, size * 0.23) : Math.max(7.5, size * 0.27));
  const uid = $props.id();  // gradienty SVG: osobne id na ikonę (folder z kłódką ma inne kolory)
</script>

<!-- Ikona „unosi się” przy najechaniu wiersza (klasa `group` na rodzicu); bez ruchu przy reduced-motion. -->
<span aria-hidden="true" class="relative inline-block flex-none transition-transform duration-300
  ease-[cubic-bezier(.2,1.4,.4,1)] group-hover:-translate-y-0.5 group-hover:-rotate-2 motion-reduce:transition-none"
  style="width:{size}px;height:{height}px">
  {#if kind === 'dir'}
    <svg viewBox="0 0 30 36" width={size} height={height} class="drop-shadow-[0_3px_5px_rgb(120_53_15/.22)]">
      <defs>
        <linearGradient id="{uid}-back" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color={locked ? '#94a3b8' : '#f59e0b'} /><stop offset="1" stop-color={locked ? '#64748b' : '#d97706'} />
        </linearGradient>
        <linearGradient id="{uid}-front" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color={locked ? '#cbd5e1' : '#fde68a'} /><stop offset="1" stop-color={locked ? '#94a3b8' : '#fbbf24'} />
        </linearGradient>
      </defs>
      <path d="M2 10.5a2.5 2.5 0 0 1 2.5-2.5h7l3 3h11a2.5 2.5 0 0 1 2.5 2.5V28a2.5 2.5 0 0 1-2.5 2.5h-21A2.5 2.5 0 0 1 2 28z" fill="url(#{uid}-back)" />
      <path d="M2 15.5A2.5 2.5 0 0 1 4.5 13h21a2.5 2.5 0 0 1 2.5 2.5V28a2.5 2.5 0 0 1-2.5 2.5h-21A2.5 2.5 0 0 1 2 28z" fill="url(#{uid}-front)" />
      <path d="M3 14.4h24" stroke="#fff" stroke-opacity=".55" stroke-width=".8" />
    </svg>
    {#if locked}
      <span data-locked class="absolute right-0 bottom-0.5 grid place-items-center rounded-full bg-surface p-[2px] text-mut shadow-[var(--shadow-raised)]">
        <Icon name="lock" size={Math.max(9, size * 0.32)} strokeWidth={2.5} />
      </span>
    {/if}
  {:else if isMedia(type)}
    {@const m = MEDIA[type]}
    <span class="absolute inset-x-0 top-[8%] bottom-[8%] grid place-items-center rounded-[22%] text-white
      shadow-[inset_0_1px_0_rgb(255_255_255/.35),0_4px_10px_-4px_rgb(30_27_75/.45)]"
      style="background:linear-gradient(135deg,{m.from},{m.to})">
      <Icon name={m.glyph} size={Math.round(size * 0.5)} strokeWidth={2.2} />
    </span>
  {:else}
    <!-- kartka z zagiętym rogiem i kolorową etykietą typu -->
    <span class="absolute inset-0 overflow-hidden rounded-[18%] bg-surface shadow-[var(--shadow-raised)]">
      <span class="absolute top-0 right-0 h-[30%] w-[30%] rounded-bl-[30%]
        bg-[linear-gradient(225deg,var(--color-bg)_50%,color-mix(in_srgb,var(--color-ink)_12%,transparent)_50%)]"></span>
      {#if type === 'apk'}
        <span class="absolute top-[18%] left-1/2 grid aspect-square w-[52%] -translate-x-1/2 place-items-center rounded-[28%] text-white
          shadow-[inset_0_1px_0_rgb(255_255_255/.3)]" style="background:linear-gradient(135deg,#2dd4bf,#0f766e)">
          <Icon name="package" size={Math.round(size * 0.32)} strokeWidth={2.4} />
        </span>
      {:else}
        <span class="absolute top-[22%] right-[30%] left-[16%] flex flex-col gap-[12%]" style="height:34%">
          <i class="block h-[2px] rounded-full bg-line"></i><i class="block h-[2px] w-[78%] rounded-full bg-line"></i>
          <i class="block h-[2px] rounded-full bg-line"></i>
        </span>
      {/if}
      <span class="absolute bottom-[9%] left-[10%] rounded-[3px] px-[3px] leading-[1.35] font-black tracking-[.02em] text-white"
        style="background:{extColor(ext)};font-size:{font}px">{label}</span>
    </span>
  {/if}
</span>
