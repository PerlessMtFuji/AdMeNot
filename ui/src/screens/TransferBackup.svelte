<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import { getContext, untrack } from 'svelte';
  import CopyNote from '../components/CopyNote.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import { formatEta } from '../lib/eta';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { backupOutcome, formatSize, isXiaomi, modelName, stableEta, transferProgress } from '../lib/logic';
  import type { TelephonyResult, TransferStage } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
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

  // --- postęp: czas do końca z tempa dotychczasowej kopii (most go nie liczy) ---
  let startedAt: number | null = null;
  let startValue = 0;
  let resumed = false;  // po rozłączeniu tempo liczymy od powrotu telefonu: czas czekania go nie zaniża
  let etaS = $state<number | null>(null);
  $effect(() => {
    const v = value;
    if (!p) { startedAt = null; etaS = null; return; }
    const now = Date.now();
    if (tr.waiting) { resumed = true; return; }
    if (resumed) { resumed = false; startedAt = now; startValue = v; return; }
    if (startedAt === null) { startedAt = now; startValue = v; return; }
    const gained = v - startValue;
    const elapsed = (now - startedAt) / 1000;
    if (gained < 0.02 || elapsed < 5) return;
    const next = Math.round((elapsed * (1 - v)) / gained);
    etaS = stableEta(untrack(() => etaS), next);
  });
  const timeLeft = $derived(etaS === null || tr.waiting ? null
    : t('transfer.time_left', { time: formatEta({ eta_s: etaS, eta_kind: 'measured', eta_min_s: null, eta_max_s: null }, i18n.lang) }));

  // --- lista etapów po prawej: tylko to, co wybrano (plus etap, który właśnie trwa), na końcu sprawdzanie ---
  const STAGES: TransferStage[] = ['telephony', 'files', 'apps', 'verify'];
  const stages = $derived.by(() => {
    const sel = tr.selection;
    const wanted = new Set<TransferStage>(['verify']);
    if (sel.contacts || sel.sms || sel.mms || sel.calls) wanted.add('telephony');
    if (sel.categories.length || sel.others.length) wanted.add('files');
    if (sel.apps.length) wanted.add('apps');
    if (wanted.size === 1) STAGES.forEach((k) => wanted.add(k)); // wybór nieznany (np. wznowienie): wszystkie etapy
    if (p) wanted.add(p.stage);
    const list = STAGES.filter((k) => wanted.has(k));
    const cur = p ? list.indexOf(p.stage) : -1;
    return list.map((key, i) => ({ key, state: (cur < 0 ? 'todo' : i < cur ? 'done' : i === cur ? 'current' : 'todo') as 'done' | 'current' | 'todo' }));
  });

  // --- koniec ---
  const TELEPHONY = ['contacts', 'sms', 'mms', 'calls'] as const;
  const telephony = $derived(done ? TELEPHONY.filter((k) => k in done.telephony).map((k) => [k, done.telephony[k]] as const) : []);
  const unavailable = $derived(telephony.some(([, r]) => r.status === 'unavailable' && r.source !== 'export'));
  const usable = $derived(outcome !== null && outcome !== 'stopped');
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const took = (sec: number) => (sec < 60 ? t('transfer.took_sec', { n: Math.max(1, Math.round(sec)) }) : t('transfer.took_min', { n: Math.round(sec / 60) }));
  const expiresOn = $derived(tr.copy ? new Date(tr.copy.expires).toLocaleDateString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB') : '');

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
    // coś się skopiowało: liczba i braki; „nie udało się” tylko gdy nie ma nic
    return [r.count > 0 ? num(r.count) : t('transfer.sum.tel_failed'), ...problems(r)].join(' · ');
  }

  const failed = (n: number) => (n > 0 ? ` · ${t('transfer.sum.failed', { count: num(n) })}` : '');

  /** Liczby wyniku w jednej linii: „Kontakty 412”, w żółtym to, co się nie udało. */
  const numbers = $derived(!done ? [] : [
    ...telephony.map(([key, r]) => ({ key, label: t(`transfer.sum.${key}`), text: telephonyText(r), warn: r.status !== 'ok', title: undefined as string | undefined })),
    { key: 'files', label: t('transfer.sum.files'),
      text: `${num(done.files_done)}${failed(done.files_failed)}${unreadableFiles > 0 ? ` · ${t('transfer.sum.unreadable', { count: num(unreadableFiles) })}` : ''}`,
      warn: done.files_failed > 0 || unreadableFiles > 0,
      title: unreadableFiles > 0 ? `${tp('transfer.unreadable_files', unreadableFiles, { count: num(unreadableFiles) })}. ${t('transfer.unreadable_files_text')}` : undefined },
    { key: 'apps', label: t('transfer.sum.apps'), text: `${num(done.apps_done)}${failed(done.apps_failed)}`, warn: done.apps_failed > 0, title: undefined },
  ]);
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
          <div class="flex items-center gap-2 text-md font-bold">
            {#if !tr.waiting}<Spinner />{/if}
            {p ? t('transfer.stage_label', { stage: t(`transfer.phase.${p.stage}`) }) : t('transfer.starting')}
          </div>
          <Progress {value} label={t('transfer.progress_label')} />
          {#if p && (counts.length || p.total_bytes > 0 || timeLeft)}
            <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-mut">
              <span>{counts.join(' · ')}{#if p.total_bytes > 0}{counts.length ? ' · ' : ''}{t('transfer.progress_size', { done: size(p.done_bytes), total: size(p.total_bytes) })}{/if}</span>
              {#if timeLeft}<span class="font-semibold tabular-nums">{timeLeft}</span>{/if}
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
      <!-- wynik jednym zdaniem: zielony, a gdy coś się nie udało — żółty z powodem -->
      <div role="status" class="flex items-center gap-3.5 rounded-2xl border px-4 py-3.5
        {outcome === 'ok' ? 'border-ok/30 bg-ok-soft' : 'border-warn-strong/40 bg-warn-soft'}">
        <span class="grid h-9 w-9 flex-none place-items-center rounded-full {outcome === 'ok' ? 'bg-ok/15 text-ok' : 'bg-warn-strong/25 text-warn'}">
          <Icon name={outcome === 'ok' ? 'check' : outcome === 'stopped' ? 'pause' : 'triangle-alert'} size={18} />
        </span>
        <div class="min-w-0 flex-1">
          {#if outcome === 'ok'}
            <b class="block text-ink">{t('transfer.done_ok')}</b>
          {:else if outcome === 'stopped'}
            <b class="block text-ink">{t('transfer.done_stopped')}</b>
            <span class="text-warn">{t('transfer.done_stopped_text')}</span>
          {:else}
            <b class="block text-ink">{t('transfer.done_warn')}</b>
            <span class="text-warn">{t('transfer.done_warn_text')}</span>
          {/if}
          {#if outcome !== 'stopped'}
            <span class="block text-sm {outcome === 'ok' ? 'text-ok' : 'text-warn'}">{t('transfer.done_took', { size: size(done.bytes), time: took(done.seconds) })}</span>
          {/if}
        </div>
      </div>

      <ul data-testid="copy-numbers" class="flex flex-wrap gap-x-5 gap-y-1 text-sm text-mut">
        {#each numbers as n (n.key)}
          <li title={n.title}>{n.label} <b class={n.warn ? 'text-warn' : 'text-ink'}>{n.text}</b></li>
        {/each}
      </ul>

      {#if unavailable}
        <!-- jedna krótka linia pod liczbami, nie osobna karta -->
        <p class="text-sm text-mut">{t('transfer.unreadable')}{#if isXiaomi(s.device)} {t('transfer.xiaomi_hint')}{/if}</p>
      {/if}

      {#if usable}
        <!-- główna rzecz: po podłączeniu innego telefonu program sam przechodzi do planu wgrywania (kontroler) -->
        <div class="flex items-center gap-4 rounded-2xl border border-accent/30 bg-surface/90 px-5 py-4 shadow-[var(--shadow-well)]">
          <span class="flex flex-none items-center gap-1.5 text-accent" aria-hidden="true">
            <i class="block h-11 w-[26px] rounded-md bg-slate-600/70"></i>
            <span class="text-lg font-bold">→</span>
            <i class="block h-11 w-[26px] rounded-md bg-accent"></i>
          </span>
          <span class="min-w-0 flex-1">
            <span class="block text-lg font-bold text-ink">{t('transfer.next_title')}</span>
            <span class="block text-mut">{t('transfer.next_text')}</span>
          </span>
        </div>
      {/if}
      {#if tr.copy}
        <div><CopyNote copy={tr.copy} addLabel={t('transfer.note.add_to_copy')} /></div>
      {/if}
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
    {#if done}
      {#if tr.copy?.order || tr.copy?.client}
        <div class="text-sm text-mut">{[tr.copy.order, tr.copy.client].filter(Boolean).join(' · ')}</div>
      {/if}
      {#if tr.copy}<p class="rounded-[10px] bg-neutral-soft px-3 py-2 text-[12.5px] text-mut">{t('transfer.expires_on', { date: expiresOn })}</p>{/if}
      <Button variant={usable ? 'secondary' : 'primary'} onclick={() => ctl.leaveTransfer()}>{usable ? t('transfer.finish_later') : t('transfer.finish')}</Button>
    {:else}
      <div class="lbl mt-1">{t('transfer.stages_label')}</div>
      <ol aria-label={t('transfer.stages_label')} class="flex flex-col gap-2 text-sm">
        {#each stages as st (st.key)}
          <li aria-current={st.state === 'current' ? 'step' : undefined}
            class="flex items-center gap-2 {st.state === 'current' ? 'font-bold text-ink' : st.state === 'done' ? 'text-mut' : 'text-soft'}">
            <span aria-hidden="true" class="grid h-[18px] w-[18px] flex-none place-items-center rounded-full text-white
              {st.state === 'done' ? 'bg-ok' : st.state === 'current' ? 'bg-accent' : 'bg-neutral-soft'}">
              {#if st.state === 'done'}<Check size={11} strokeWidth={3} />{:else if st.state === 'current'}<i class="block h-1.5 w-1.5 rounded-full bg-white"></i>{/if}
            </span>
            {#if st.state === 'done'}<span class="sr-only">{t('transfer.stage_done')}</span>{/if}
            {t(`transfer.phase.${st.key}`)}
          </li>
        {/each}
      </ol>
    {/if}
  </SidePanel>
</div>
