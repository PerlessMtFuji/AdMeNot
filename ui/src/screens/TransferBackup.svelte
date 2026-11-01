<script lang="ts">
  import { getContext } from 'svelte';
  import CopyNote from '../components/CopyNote.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { backupOutcome, formatSize, isXiaomi, modelName, transferProgress } from '../lib/logic';
  import type { TelephonyResult } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Progress from '../ui/Progress.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const tr = $derived(s.transfer);
  const p = $derived(tr.progress);
  const done = $derived(s.phase === 'transfer_done' ? tr.result : null);
  const unreadableFiles = $derived(tr.copy?.counts.unreadable ?? 0);
  const outcome = $derived(done ? backupOutcome(done, unreadableFiles) : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const value = $derived(transferProgress(p));
  // „10 z 10 plików · 4 z 35 aplikacji”: pliki kończą się przed aplikacjami, sama liczba plików myli
  const counts = $derived(!p ? [] : [
    ...(p.total_files > 0 ? [tp('transfer.progress_files', p.total_files, { done: num(p.done_files), count: num(p.total_files) })] : []),
    ...(p.total_apps ? [tp('transfer.progress_apps', p.total_apps, { done: num(p.done_apps ?? 0), count: num(p.total_apps) })] : []),
  ]);
  const TELEPHONY = ['contacts', 'sms', 'mms', 'calls'] as const;
  const telephony = $derived(done ? TELEPHONY.filter((k) => k in done.telephony).map((k) => [k, done.telephony[k]] as const) : []);
  const unavailable = $derived(telephony.some(([, r]) => r.status === 'unavailable' && r.source !== 'export'));

  const size = (bytes: number) => formatSize(bytes, i18n.lang);

  const KNOWN_ERRORS = ['addresses_missing', 'attachments_missing', 'export_changed', 'export_invalid'];

  /** `addresses_missing:3,attachments_missing:1`, `export_changed` → czytelne braki; nieznane fragmenty pomijamy. */
  function problems(r: TelephonyResult): string[] {
    return (r.error ?? '').split(',').flatMap((part) => {
      const [key, n] = part.split(':');
      return KNOWN_ERRORS.includes(key) ? [t(`transfer.sum.${key}`, { count: n ?? '' })] : [];
    });
  }

  /** Dane z pliku eksportu: dopisek przy liczbie zamiast podpowiedzi o Xiaomi. */
  function telephonyText(r: TelephonyResult): string {
    if (r.status === 'ok') return r.source === 'export' ? `${num(r.count)} · ${t('transfer.export.from_file')}` : num(r.count);
    if (r.status === 'unavailable') return t('transfer.unavailable');
    return [t('transfer.sum.tel_failed'), ...problems(r)].join(' · ');
  }

  const failed = (n: number) => (n > 0 ? ` · ${t('transfer.sum.failed', { count: num(n) })}` : '');
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-4 scroll-fade overflow-auto px-7 py-7">
    <div>
      <div class="text-sm font-semibold text-soft">{crumb}</div>
      <h1 class="text-2xl font-extrabold">{done ? t('transfer.done_heading') : t('transfer.copying')}</h1>
      {#if !done}<p class="text-mut">{t('transfer.copying_sub')}</p>{/if}
    </div>

    {#if !done}
      {#if tr.waiting}<Banner tone="warn" icon="triangle-alert" title={t('transfer.waiting')} />{/if}
      <Card>
        <div class="flex flex-col gap-3 px-5 py-4">
          <div class="flex items-center gap-2 font-semibold">
            {#if !tr.waiting}<Spinner />{/if}
            {p ? t('transfer.stage_label', { stage: t(`transfer.phase.${p.stage}`) }) : t('transfer.starting')}
          </div>
          <Progress {value} label={t('transfer.progress_label')} />
          {#if p && counts.length}
            <div class="flex flex-wrap justify-between gap-2 text-sm text-mut">
              <span>{counts.join(' · ')}</span>
              {#if p.total_bytes > 0}<span>{t('transfer.progress_size', { done: size(p.done_bytes), total: size(p.total_bytes) })}</span>{/if}
            </div>
          {/if}
          {#if p?.current}<div class="mono truncate text-xs text-soft" title={p.current}>{p.current}</div>{/if}
        </div>
      </Card>
      {@render note()}
      <div>
        <Button disabled={s.stopping || s.job?.kind !== 'backup'} onclick={() => ctl.stopBackup()}>
          {s.stopping ? t('transfer.stopping') : t('transfer.stop')}
        </Button>
      </div>
    {:else}
      {#if outcome === 'ok'}
        <Banner tone="ok" icon="check" title={t('transfer.done_ok')} />
      {:else if outcome === 'stopped'}
        <Banner tone="warn" icon="pause" title={t('transfer.done_stopped')}>{t('transfer.done_stopped_text')}</Banner>
      {:else}
        <Banner tone="warn" icon="triangle-alert" title={t('transfer.done_warn')}>{t('transfer.done_warn_text')}</Banner>
      {/if}
      {#if unavailable && isXiaomi(s.device)}
        <Banner tone="warn" icon="info" title={t('transfer.unreadable')}>{t('transfer.xiaomi_hint')}</Banner>
      {:else if unavailable}
        <Banner tone="warn" icon="info" title={t('transfer.unreadable')} />
      {/if}
      {#if unreadableFiles > 0}
        <Banner tone="warn" icon="info" title={tp('transfer.unreadable_files', unreadableFiles, { count: num(unreadableFiles) })}>
          {t('transfer.unreadable_files_text')}
        </Banner>
      {/if}

      <Card>
        <dl class="flex flex-col gap-1.5 px-5 py-4 text-sm">
          {#each telephony as [key, r] (key)}
            <div class="flex justify-between gap-3">
              <dt class="text-mut">{t(`transfer.sum.${key}`)}</dt>
              <dd class="font-bold {r.status === 'ok' ? '' : 'text-warn'}">{telephonyText(r)}</dd>
            </div>
          {/each}
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.sum.files')}</dt>
            <dd class="font-bold {done.files_failed ? 'text-warn' : ''}">{num(done.files_done)}{failed(done.files_failed)}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.sum.apps')}</dt>
            <dd class="font-bold {done.apps_failed ? 'text-warn' : ''}">{num(done.apps_done)}{failed(done.apps_failed)}</dd>
          </div>
          <div class="flex justify-between gap-3">
            <dt class="text-mut">{t('transfer.sum.size')}</dt><dd class="font-bold">{size(done.bytes)}</dd>
          </div>
        </dl>
      </Card>
      {@render note()}
      {#if tr.copy}<p class="text-sm text-mut">{tp('transfer.expires', tr.copy.days_left)}</p>{/if}
      <div><Button variant="primary" onclick={() => ctl.leaveTransfer()}>{t('transfer.finish')}</Button></div>
    {/if}
  </main>

  {#snippet note()}
    {#if tr.copy}
      <section aria-label={t('transfer.note.label')} class="rounded-2xl card px-5 py-3">
        <span class="lbl">{t('transfer.note.label')}</span>
        <CopyNote copy={tr.copy} />
      </section>
    {/if}
  {/snippet}

  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.device?.serial ?? s.serial ?? ''} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected={!tr.waiting} />
  </SidePanel>
</div>
