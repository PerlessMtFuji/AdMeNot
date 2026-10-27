<script lang="ts">
  import { getContext } from 'svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize, modelName, restoreOutcome } from '../lib/logic';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Progress from '../ui/Progress.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const r = $derived(s.transfer.restore);
  const p = $derived(r.progress);
  const done = $derived(s.phase === 'transfer_restored' ? r.result : null);
  const outcome = $derived(done ? restoreOutcome(done) : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const value = $derived(!p ? 0 : p.total_bytes > 0 ? p.done_bytes / p.total_bytes
    : p.total_files > 0 ? p.done_files / p.total_files : 0);

  // Uwagi pod liczbami: tylko niezerowe; ostrzeżenia (odmowy, błędy, braki) na żółto.
  const notes = $derived.by((): { text: string; warn: boolean }[] => {
    if (!done) return [];
    const line = (n: number, key: string, warn = false) => (n > 0 ? [{ text: t(`transfer.restore.sum.${key}`, { count: num(n) }), warn }] : []);
    return [
      ...line(done.files_renamed, 'renamed'),
      ...line(done.files_denied, 'denied', true),
      ...line(done.files_failed, 'failed', true),
      ...line(done.files_missing, 'missing', true),
      ...line(done.files_unselected, 'unselected'),
      ...(done.apk_skipped > 0 ? [{ text: tp('transfer.restore.apk_skipped', done.apk_skipped, { count: num(done.apk_skipped) }), warn: false }] : []),
      ...line(done.apk_suspicious_skipped, 'suspicious'),
    ];
  });
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-4 scroll-fade overflow-auto px-7 py-7">
    <div>
      <div class="text-sm font-semibold text-soft">{crumb}</div>
      <h1 class="text-2xl font-extrabold">{done ? t('transfer.restore.done_heading') : t('transfer.restore.uploading')}</h1>
      {#if !done}<p class="text-mut">{t('transfer.restore.uploading_sub')}</p>{/if}
    </div>

    {#if !done}
      {#if s.transfer.waiting}<Banner tone="warn" icon="triangle-alert" title={t('transfer.restore.waiting')} />{/if}
      <Card>
        <div class="flex flex-col gap-3 px-5 py-4">
          <div class="flex items-center gap-2 font-semibold">
            {#if !s.transfer.waiting}<Spinner />{/if}
            {p ? t('transfer.stage_label', { stage: t(`transfer.restore.phase.${p.stage}`) }) : t('transfer.restore.starting')}
          </div>
          <Progress {value} label={t('transfer.restore.progress_label')} />
          {#if p && p.total_files > 0}
            <div class="flex flex-wrap justify-between gap-2 text-sm text-mut">
              <span>{tp('transfer.progress_files', p.total_files, { done: num(p.done_files), count: num(p.total_files) })}</span>
              {#if p.total_bytes > 0}<span>{t('transfer.progress_size', { done: size(p.done_bytes), total: size(p.total_bytes) })}</span>{/if}
            </div>
          {/if}
          {#if p?.current}<div class="mono truncate text-xs text-soft" title={p.current}>{p.current}</div>{/if}
        </div>
      </Card>
      <div>
        <Button disabled={s.stopping || s.job?.kind !== 'restore'} onclick={() => ctl.stopRestore()}>
          {s.stopping ? t('transfer.stopping') : t('transfer.stop')}
        </Button>
      </div>
    {:else}
      {#if outcome === 'ok'}
        <Banner tone="ok" icon="check" title={t('transfer.restore.done_ok')} />
      {:else if outcome === 'stopped'}
        <Banner tone="warn" icon="pause" title={t('transfer.restore.done_stopped')}>{t('transfer.restore.done_stopped_text')}</Banner>
      {:else if outcome === 'scan'}
        <Banner tone="warn" icon="info" title={t('transfer.restore.scan_failed')}>{t('transfer.restore.scan_failed_text')}</Banner>
      {:else}
        <Banner tone="warn" icon="triangle-alert" title={t('transfer.restore.done_warn')}>{t('transfer.restore.done_warn_text')}</Banner>
      {/if}
      <!-- „skipped” = przebieg się nie skończył: galerię odświeży wznowienie, bez prośby o restart -->
      {#if done.media_scan === 'restart'}
        <Banner tone="warn" icon="rotate-ccw" title={t('transfer.restore.restart')}>{t('transfer.restore.restart_text')}</Banner>
      {:else if done.media_scan === 'failed' && outcome !== 'scan'}
        <Banner tone="warn" icon="info" title={t('transfer.restore.scan_failed')}>{t('transfer.restore.scan_failed_text')}</Banner>
      {/if}

      <Card>
        <dl class="flex flex-col gap-1.5 px-5 py-4 text-sm">
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.restore.sum.done')}</dt><dd class="font-bold">{num(done.files_done)}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.restore.sum.exists')}</dt><dd class="font-bold">{num(done.files_exists)}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.restore.sum.size')}</dt><dd class="font-bold">{size(done.bytes)}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.restore.sum.checked')}</dt>
            <dd class="font-bold">{t(done.hashed ? 'transfer.restore.sum.checked_hash' : 'transfer.restore.sum.checked_size')}</dd>
          </div>
        </dl>
        {#if notes.length}
          <ul class="flex flex-col gap-1 border-t border-line px-5 py-3 text-sm">
            {#each notes as n (n.text)}<li class={n.warn ? 'font-semibold text-warn' : 'text-mut'}>{n.text}</li>{/each}
          </ul>
        {/if}
      </Card>
      <div><Button variant="primary" onclick={() => ctl.leaveTransfer()}>{t('transfer.finish')}</Button></div>
    {/if}
  </main>

  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.device?.serial ?? s.serial ?? ''} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected={!s.transfer.waiting} />
  </SidePanel>
</div>
