<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { MATCH_KEYS, t } from '../lib/i18n/index.svelte';
  import { formatUptime } from '../lib/logic';

  const s = getContext<Controller>('ctl').state;
  const expert = $derived(s.settings.mode === 'expert');
  const busy = $derived(s.phase === 'scanning' || s.apk.running);
  const known: readonly string[] = MATCH_KEYS;
  const match = $derived(s.device?.match && known.includes(s.device.match.confidence)
    ? s.device.match.confidence : 'none');
</script>

{#if s.device}
  <aside class="card hard flex w-[210px] flex-none flex-col gap-2 self-start">
    <span class="lbl">{t('phone.subject')}</span>
    <div class="relative grid h-[170px] place-items-center overflow-hidden rounded-lg bg-gradient-to-b from-[#f5f8fb] to-[#e9eef4]">
      {#if busy}<div class="scanline"></div>{/if}
      <img class="max-h-[150px] drop-shadow-[0_8px_10px_rgba(29,39,51,.25)]" src={s.device.image} alt={s.device.name} />
    </div>
    <b class="text-[13px]">{match === 'approximate' ? '~ ' : ''}{s.device.name}</b>
    <dl class="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px] {expert ? 'mono' : ''}">
      {#if expert}
        <dt class="text-mut">{t('phone.model')}</dt><dd class="font-semibold">{s.device.model}</dd>
        <dt class="text-mut">{t('phone.match')}</dt><dd class="font-semibold">{t(`match.${match}`)}</dd>
        <dt class="text-mut">{t('phone.serial')}</dt><dd class="font-semibold break-all">{s.device.serial}</dd>
        <dt class="text-mut">{t('phone.sdk')}</dt><dd class="font-semibold">{s.device.sdk} · Android {s.device.android}</dd>
        <dt class="text-mut">{t('phone.uptime')}</dt><dd class="font-semibold">{formatUptime(s.device.uptime_s)}</dd>
        <dt class="text-mut">{t('phone.patch')}</dt><dd class="font-semibold">{s.device.patch ?? '—'}</dd>
        <dt class="text-mut">{t('phone.oem')}</dt><dd class="font-semibold">{s.device.manufacturer}</dd>
      {:else}
        <dt class="text-mut">{t('phone.android')}</dt><dd class="font-semibold">{s.device.android}</dd>
        <dt class="text-mut">{t('phone.connection')}</dt><dd class="ok font-semibold">{t('phone.connected')}</dd>
        {#if s.scan}
          <dt class="text-mut">{t('phone.apps')}</dt>
          <dd class="font-semibold">{t('phone.apps_value', { total: s.scan.counts.total, user: s.scan.counts.user })}</dd>
        {/if}
      {/if}
    </dl>
  </aside>
{/if}
