<script lang="ts">
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import type { PlaceView, StorageView } from '../../lib/types';
  import Icon, { type IconName } from '../../ui/Icon.svelte';
  import PhoneStorage from './PhoneStorage.svelte';

  type Props = { places: PlaceView[]; recent: string[]; path: string; storage?: StorageView | null; busy?: boolean; ongo: (path: string) => void };
  let { places, recent, path, storage = null, busy = false, ongo }: Props = $props();

  // Ikona i barwa rodzaju danych (spec §5.6 — „Miejsca z ikoną i kolorem rodzaju”).
  const LOOK: Record<PlaceView['icon'], { icon: IconName; color: string }> = {
    camera: { icon: 'camera', color: '#16a34a' }, screenshot: { icon: 'scan-line', color: '#2563eb' },
    download: { icon: 'download', color: '#d97706' }, chat: { icon: 'message-circle', color: '#059669' },
    film: { icon: 'film', color: '#e11d48' }, music: { icon: 'music', color: '#7c3aed' },
    document: { icon: 'file-text', color: '#0891b2' }, phone: { icon: 'hard-drive', color: '#4f46e5' },
  };
  const ROW = 'group flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left text-sm font-semibold transition duration-150';
  const count = (n: number) => n.toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB');
  // „Ostatnio”: bez folderów, które już są Miejscami.
  const recentShown = $derived(recent.filter((p) => !places.some((pl) => pl.path === p)).slice(0, 5));
  const tail = (p: string) => p.slice(p.lastIndexOf('/') + 1);
</script>

<aside class="flex w-[188px] flex-none flex-col gap-4 overflow-y-auto rounded-2xl card p-2.5 max-[1200px]:w-[168px]">
  <nav aria-label={t('explorer.places_label')} class="flex flex-col gap-0.5">
    <div class="lbl px-2 pb-1">{t('explorer.places_label')}</div>
    {#each places as p (p.key)}
      {@const look = LOOK[p.icon] ?? LOOK.phone}
      {@const on = p.path === path}
      <button type="button" aria-current={on ? 'location' : undefined} onclick={() => ongo(p.path)}
        class="{ROW} {on ? 'rail-now text-accent' : 'text-mut hover:bg-neutral-soft hover:text-ink'}">
        <span class="grid h-[26px] w-[26px] flex-none place-items-center rounded-lg text-white transition-transform duration-300
          ease-[cubic-bezier(.2,1.4,.4,1)] group-hover:scale-110 motion-reduce:transition-none
          shadow-[inset_0_1px_0_rgb(255_255_255/.3),0_3px_8px_-3px_var(--c)]"
          style="--c:{look.color};background:linear-gradient(135deg,color-mix(in srgb,{look.color} 70%,white),{look.color})">
          <Icon name={look.icon} size={14} strokeWidth={2.4} />
        </span>
        <span class="min-w-0 flex-1 truncate">{t(`explorer.place.${p.key}`)}</span>
        {#if p.count !== null}
          <small class="flex-none text-2xs font-semibold tabular-nums {on ? 'text-accent' : 'text-soft'}">{count(p.count)}</small>
        {:else}
          <small class="h-1.5 w-1.5 flex-none rounded-full bg-line" title={t('explorer.counting')}></small>
        {/if}
      </button>
    {/each}
  </nav>
  {#if recentShown.length}
    <nav aria-label={t('explorer.recent_label')} class="flex flex-col gap-0.5">
      <div class="lbl px-2 pb-1">{t('explorer.recent_label')}</div>
      {#each recentShown as r (r)}
        <button type="button" title={r.replace(/^\/sdcard\/?/, '')} aria-current={r === path ? 'location' : undefined}
          onclick={() => ongo(r)}
          class="{ROW} {r === path ? 'rail-now text-accent' : 'text-mut hover:bg-neutral-soft hover:text-ink'}">
          <Icon name="folder" size={15} class="text-warn-strong" />
          <span class="min-w-0 flex-1 truncate">{tail(r)}</span>
        </button>
      {/each}
    </nav>
  {/if}
  <div class="mt-auto"><PhoneStorage usage={storage} {busy} /></div>
</aside>
