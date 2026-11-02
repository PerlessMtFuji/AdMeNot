<script lang="ts">
  import { getContext } from 'svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import TapPrompt, { smsAppName } from '../components/TapPrompt.svelte';
  import type { Controller } from '../lib/controller';
  import { ERROR_KEYS, i18n, RESTORE_ERROR_KEYS, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize, modelName, restoreOutcome, telOutcome } from '../lib/logic';
  import type { TelCategory } from '../lib/types';
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
  const tp_ = $derived(r.telProgress);
  // Kopia bezpieczeństwa nowego telefonu (minuty, bez liczników): pasek bez procentów zamiast 0 %.
  const value = $derived(tp_?.kind === 'safety' ? null : tp_ ? (tp_.total > 0 ? tp_.done / tp_.total : 0)
    : !p ? 0 : p.total_bytes > 0 ? p.done_bytes / p.total_bytes : p.total_files > 0 ? p.done_files / p.total_files : 0);

  // Etapy: Pliki → Kontakty → Wiadomości → Połączenia (tylko wybrane); telefonia idzie po plikach.
  type Stage = 'files' | 'safety' | 'contacts' | 'messages' | 'calls';
  const stageOf = (k: TelCategory): Stage => (k === 'sms' || k === 'mms' ? 'messages' : k);
  const stages = $derived.by((): { key: Stage; state: 'done' | 'current' | 'todo' }[] => {
    const files: Stage[] = r.choice.groups.length ? ['files'] : [];
    const tel: Stage[] = r.choice.tel.map((k) => stageOf(k));
    // Kopia bezpieczeństwa nowego telefonu idzie tuż przed pierwszą kategorią telefonii: w trakcie jest
    // osobnym bieżącym etapem (nie „Kontakty”).
    const safety = tp_?.kind === 'safety';
    const list: Stage[] = [...files, ...(safety ? ['safety' as const] : []), ...tel];
    if (files.length + tel.length < 2) return [];
    const cur: Stage = !tp_ ? 'files' : tp_.kind === 'safety' ? 'safety' : stageOf(tp_.kind);
    const at = Math.max(0, list.indexOf(cur));
    return list.map((key, i) => ({ key, state: i < at ? 'done' : i === at ? 'current' : 'todo' }));
  });
  const stageLabel = $derived(tp_ ? t(`transfer.restore.stage.${tp_.kind === 'safety' ? 'safety' : stageOf(tp_.kind)}`)
    : p ? t(`transfer.restore.phase.${p.stage}`) : null);

  // Telefonia w wyniku: tabela kategorii, kroki do zrobienia na telefonie i stan sprzątania.
  const tel = $derived(done ? r.telResult : null);
  const telState = $derived(tel ? telOutcome(tel) : null);
  const TEL_ORDER: TelCategory[] = ['contacts', 'sms', 'mms', 'calls'];
  const telRows = $derived(tel ? TEL_ORDER.flatMap((k) => (tel.kinds[k] ? [{ kind: k, ...tel.kinds[k]! }] : [])) : []);
  const restoreKeys: readonly string[] = RESTORE_ERROR_KEYS;
  const knownKeys: readonly string[] = ERROR_KEYS;
  const telErrorText = $derived(!done || !r.telError ? null
    : restoreKeys.includes(r.telError) ? t(`transfer.restore.error.${r.telError}`)
    : t(`error.${knownKeys.includes(r.telError) ? r.telError : 'internal'}`, { device: '' }));
  // Bez wybranych plików (sama telefonia) nie ma czego pokazać w wyniku plików.
  const showFiles = $derived(r.choice.groups.length > 0 || (!tel && !r.telError));

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
            {stageLabel ? t('transfer.stage_label', { stage: stageLabel }) : t('transfer.restore.starting')}
          </div>
          {#if stages.length}
            <ol aria-label={t('transfer.restore.stages_label')} class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              {#each stages as st, i (st.key)}
                <li data-state={st.state} class="{i > 0 ? "before:mr-2 before:text-soft before:content-['→']" : ''}
                  {st.state === 'current' ? 'font-bold text-ink' : st.state === 'done' ? 'text-ok' : 'text-soft'}">
                  {t(`transfer.restore.stage.${st.key}`)}
                </li>
              {/each}
            </ol>
          {/if}
          <Progress {value} label={t('transfer.restore.progress_label')} />
          {#if tp_}
            {#if tp_.kind !== 'safety'}
              <div class="text-sm text-mut">{t('transfer.restore.tel_progress', { done: num(tp_.done), total: num(tp_.total) })}</div>
            {/if}
          {:else if p && p.total_files > 0}
            <div class="flex flex-wrap justify-between gap-2 text-sm text-mut">
              <span>{tp('transfer.progress_files', p.total_files, { done: num(p.done_files), count: num(p.total_files) })}</span>
              {#if p.total_bytes > 0}<span>{t('transfer.progress_size', { done: size(p.done_bytes), total: size(p.total_bytes) })}</span>{/if}
            </div>
          {/if}
          {#if !tp_ && p?.current}<div class="mono truncate text-xs text-soft" title={p.current}>{p.current}</div>{/if}
        </div>
      </Card>
      <TapPrompt />
      <div>
        <Button disabled={s.stopping || s.job?.kind !== 'restore'} onclick={() => ctl.stopRestore()}>
          {s.stopping ? t('transfer.stopping') : t('transfer.stop')}
        </Button>
      </div>
    {:else}
      {#if showFiles}
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
      {/if}

      {#if telErrorText}
        <Banner tone="bad" icon="triangle-alert" title={t('transfer.restore.tel.error_title')}>{telErrorText}</Banner>
      {/if}
      {#if tel}
        {#if telState === 'error'}
          <Banner tone="bad" icon="triangle-alert" title={t('transfer.restore.cleanup.failed')}>
            {t('transfer.restore.cleanup.failed_text', { app: smsAppName(r.tapPackage) })}
          </Banner>
        {:else if telState === 'warn'}
          <Banner tone="warn" icon="triangle-alert" title={t('transfer.restore.tel.done_warn')}>{t('transfer.restore.tel.done_warn_text')}</Banner>
        {:else}
          <Banner tone="ok" icon="check" title={t('transfer.restore.tel.done_ok')} />
        {/if}
        {#if tel.manual.length}
          <Banner tone="warn" icon="smartphone" title={t('transfer.restore.tel.todo_title')}>
            <ul class="mt-1 flex flex-col gap-1">
              {#each tel.manual as m (m.kind + m.name)}
                <li><b>{t(`transfer.restore.tel.kind.${m.kind}`)}:</b> {m.kind === 'contacts' ? t('transfer.restore.tel.todo_contacts', { name: m.name })
                  : t('transfer.restore.tel.todo_file', { name: m.name })}</li>
              {/each}
            </ul>
          </Banner>
        {/if}
        <Card>
          <table class="w-full text-sm">
            <thead>
              <tr class="text-left text-mut">
                {#each ['kind', 'written', 'existed', 'skipped', 'failed', 'manual', 'path'] as c (c)}
                  <th class="px-5 py-2 font-semibold {c === 'kind' || c === 'path' ? '' : 'text-right'}">{t(`transfer.restore.tel.col.${c}`)}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each telRows as row (row.kind)}
                <tr class="border-t border-line">
                  <td class="px-5 py-2 font-bold">{t(`transfer.restore.tel.kind.${row.kind}`)}</td>
                  <td class="px-5 py-2 text-right">{num(row.written)}</td>
                  <td class="px-5 py-2 text-right">{num(row.existed)}</td>
                  <td class="px-5 py-2 text-right">{num(row.skipped_synced + row.skipped_messenger)}</td>
                  <td class="px-5 py-2 text-right {row.failed ? 'font-semibold text-warn' : ''}">{num(row.failed)}</td>
                  <td class="px-5 py-2 text-right">{num(row.manual)}</td>
                  <td class="px-5 py-2">{t(`transfer.restore.tel.path.${row.path}`)}{#if row.visible_warning}<span
                    class="block font-semibold text-warn">{t('transfer.restore.tel.visible')}</span>{/if}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </Card>
      {/if}
      <div><Button variant="primary" onclick={() => ctl.leaveTransfer()}>{t('transfer.finish')}</Button></div>
    {/if}
  </main>

  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.device?.serial ?? s.serial ?? ''} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected={!s.transfer.waiting} />
  </SidePanel>
</div>
