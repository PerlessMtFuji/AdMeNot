<script lang="ts">
  import Check from '@lucide/svelte/icons/check';
  import ImageIcon from '@lucide/svelte/icons/image';
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
  import MessageCircle from '@lucide/svelte/icons/message-circle';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import Phone from '@lucide/svelte/icons/phone';
  import Users from '@lucide/svelte/icons/users';
  import { getContext, type Component } from 'svelte';
  import CategoryGroup from '../components/transfer/CategoryGroup.svelte';
  import CategoryRow from '../components/transfer/CategoryRow.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import ReportButton from '../components/ReportButton.svelte';
  import TapPrompt, { smsAppName } from '../components/TapPrompt.svelte';
  import type { Controller } from '../lib/controller';
  import { ERROR_KEYS, i18n, RESTORE_ERROR_KEYS, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize, modelName, restoreOutcome, telOutcome } from '../lib/logic';
  import { recheck } from '../lib/recheck';
  import type { AppsResultRow, TelCategory, TelKindResultView } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Progress from '../ui/Progress.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Glyph = Component<{ size?: number; strokeWidth?: number; 'aria-hidden'?: 'true' }>;
  type Tone = 'ok' | 'warn' | 'bad' | 'mut';

  /** Ile aplikacji z problemem wymieniamy w linii wiersza; reszta to „… i N innych”. */
  const APP_LISTED = 3;
  const WHATSAPP_PACKAGES = ['com.whatsapp', 'com.whatsapp.w4b'];
  const APP_WHY: readonly string[] = ['user_restricted', 'no_consent', 'too_old', 'too_new', 'no_abi', 'no_space', 'version_downgrade',
    'conflict', 'invalid_apk', 'disconnected', 'incomplete'];

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const r = $derived(s.transfer.restore);
  const p = $derived(r.progress);
  const ap = $derived(r.appsProgress);
  const done = $derived(s.phase === 'transfer_restored' ? r.result : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const took = (sec: number) => (sec < 60 ? t('transfer.took_sec', { n: Math.max(1, Math.round(sec)) }) : t('transfer.took_min', { n: Math.round(sec / 60) }));
  const ofText = (a: number, b: number) => t('transfer.restore.tel_progress', { done: num(a), total: num(b) });
  const tp_ = $derived(r.telProgress);
  // Kopia bezpieczeństwa nowego telefonu (minuty, bez liczników): pasek bez procentów zamiast 0 %.
  const value = $derived(ap ? (ap.total > 0 ? ap.done / ap.total : 0) : tp_?.kind === 'safety' ? null : tp_ ? (tp_.total > 0 ? tp_.done / tp_.total : 0)
    : !p ? 0 : p.total_bytes > 0 ? p.done_bytes / p.total_bytes : p.total_files > 0 ? p.done_files / p.total_files : 0);

  // --- Postęp. Etapy: Pliki → Kopia bezpieczeństwa → Kontakty → Wiadomości → Połączenia → Aplikacje (tylko wybrane).
  type Stage = 'files' | 'safety' | 'contacts' | 'messages' | 'calls' | 'apps';
  const stageOf = (k: TelCategory): Stage => (k === 'sms' || k === 'mms' ? 'messages' : k);
  const stages = $derived.by((): { key: Stage; state: 'done' | 'current' | 'todo' }[] => {
    const files: Stage[] = r.choice.groups.length ? ['files'] : [];
    const tel: Stage[] = r.choice.tel.map((k) => stageOf(k));
    const apps: Stage[] = r.choice.apps.length ? ['apps'] : [];
    // Kopia bezpieczeństwa nowego telefonu idzie tuż przed pierwszą kategorią telefonii: w trakcie jest
    // osobnym bieżącym etapem (nie „Kontakty”).
    const safety = tp_?.kind === 'safety';
    const list: Stage[] = [...files, ...(safety ? ['safety' as const] : []), ...tel, ...apps];
    if (files.length + tel.length + apps.length < 2) return [];
    const cur: Stage = ap ? 'apps' : !tp_ ? 'files' : tp_.kind === 'safety' ? 'safety' : stageOf(tp_.kind);
    const at = Math.max(0, list.indexOf(cur));
    return list.map((key, i) => ({ key, state: i < at ? 'done' : i === at ? 'current' : 'todo' }));
  });
  const stageLabel = $derived(ap ? t('transfer.restore.stage.apps')
    : tp_ ? t(`transfer.restore.stage.${tp_.kind === 'safety' ? 'safety' : stageOf(tp_.kind)}`)
    : p ? t(`transfer.restore.phase.${p.stage}`) : null);

  // --- Wynik
  const restoreKeys: readonly string[] = RESTORE_ERROR_KEYS;
  const knownKeys: readonly string[] = ERROR_KEYS;
  const errorText = (key: string) => restoreKeys.includes(key) ? t(`transfer.restore.error.${key}`)
    : t(`error.${knownKeys.includes(key) ? key : 'internal'}`, { device: '' });
  const tel = $derived(done ? r.telResult : null);
  const telState = $derived(tel ? telOutcome(tel) : null);
  const outcome = $derived(done ? restoreOutcome(done) : null);
  const apps = $derived(done ? r.appsResult : null);
  const appsError = $derived(done ? r.appsError : null);
  // Dokończenie nie ma szans (błąd trwały): bez etykiety i obietnicy „sprawdzę sam”.
  const gaveUp = $derived(r.reinstallGaveUp);
  const telError = $derived(done && !tel ? r.telError : null);
  // Dokończenie aplikacji po odblokowaniu Xiaomi (zadanie `restore_apps`): wiersz pokazuje postęp, nie etykietę blokady.
  const reinstalling = $derived(s.job?.kind === 'restore_apps');
  // Bez wybranych plików (sama telefonia albo same aplikacje) nie ma czego pokazać w wierszu plików.
  const showFiles = $derived(r.choice.groups.length > 0 || (!tel && !r.telError && !apps && !appsError));

  /** Wynik jednej kategorii telefonii: sumy SMS i MMS razem (jeden wiersz „SMS i MMS”). */
  function mergeKinds(a?: TelKindResultView, b?: TelKindResultView): TelKindResultView | null {
    if (!a || !b) return a ?? b ?? null;
    return { written: a.written + b.written, existed: a.existed + b.existed, skipped_synced: a.skipped_synced + b.skipped_synced,
      skipped_messenger: a.skipped_messenger + b.skipped_messenger, failed: a.failed + b.failed, manual: a.manual + b.manual,
      path: a.path === 'file' || b.path === 'file' ? 'file' : a.path !== 'none' ? a.path : b.path,
      visible_warning: a.visible_warning || b.visible_warning };
  }

  type StageMark = { key: Stage; tone: 'ok' | 'warn'; note?: string };
  type TelRow = { kind: 'contacts' | 'sms' | 'calls'; icon: Glyph; name: string; sub?: string; result: { text: string; tone: Tone };
    importPill: boolean; visible: boolean; instructions: string[]; details: string[]; mark: StageMark };
  const TEL_ICONS: Record<TelRow['kind'], Glyph> = { contacts: Users, sms: MessageSquare, calls: Phone };
  const telRows = $derived.by((): TelRow[] => {
    if (!tel) return [];
    return (['contacts', 'sms', 'calls'] as const).flatMap((kind) => {
      const k = kind === 'sms' ? mergeKinds(tel.kinds.sms, tel.kinds.mms) : tel.kinds[kind] ?? null;
      if (!k) return [];
      const present = k.written + k.existed;
      const manual = tel.manual.filter((m) => (kind === 'sms' ? m.kind === 'sms' || m.kind === 'mms' : m.kind === kind));
      const toImport = k.manual > 0 || manual.length > 0;
      const result = k.failed > 0 ? { text: ofText(present, present + k.failed + k.manual), tone: 'warn' as const }
        : toImport ? { text: num(k.manual), tone: 'warn' as const } : { text: `✓ ${num(present)}`, tone: 'ok' as const };
      const sub = [toImport ? t('transfer.restore.res.import_sub') : '', k.failed > 0 ? t('transfer.restore.sum.failed', { count: num(k.failed) }) : '',
        k.visible_warning ? t('transfer.restore.tel.visible') : ''].filter(Boolean).join(' · ') || undefined;
      const details: string[] = [];
      if (k.existed > 0) details.push(t('transfer.restore.exists', { count: num(k.existed) }));
      if (kind === 'contacts' && k.skipped_synced > 0) {
        for (const a of tel.synced_accounts) details.push(tp('transfer.restore.tel.synced', a.count, { count: num(a.count), account: a.account }));
      }
      if (k.skipped_messenger > 0) details.push(tp('transfer.restore.tel.messenger', k.skipped_messenger, { count: num(k.skipped_messenger) }));
      if (details.length && k.path !== 'none') details.push(t('transfer.restore.res.path', { path: t(`transfer.restore.tel.path.${k.path}`) }));
      const bad = k.failed > 0 || toImport;
      return [{ kind, icon: TEL_ICONS[kind], name: t(`transfer.restore.tel.${kind}`), sub, result, importPill: toImport && k.failed === 0, visible: k.visible_warning,
        instructions: manual.map((m) => (m.kind === 'contacts' ? t('transfer.restore.tel.todo_contacts', { name: m.name })
          : t('transfer.restore.tel.todo_file', { name: m.name }))),
        details: details.length === 0 || (k.existed === 0 && k.skipped_synced === 0 && k.skipped_messenger === 0) ? [] : details,
        mark: { key: stageOf(kind), tone: bad || k.visible_warning ? 'warn' : 'ok',
          note: k.failed > 0 ? t('transfer.restore.res.stage_note.failed', { count: num(k.failed) })
            : toImport ? t('transfer.restore.res.stage_note.import') : k.visible_warning ? t('transfer.restore.res.stage_note.check') : undefined } }];
    });
  });
  const telErrorText = $derived(telError ? errorText(telError) : null);
  const telFailed = $derived(tel ? telRows.some((row) => row.result.tone === 'warn' && !row.importPill) || tel.stopped
    || (tel.status === 'incomplete' && !telRows.some((row) => row.result.tone === 'warn')) : false);
  const safetyFailed = $derived(tel ? Object.keys(tel.safety).length > 0 && !Object.values(tel.safety).every(Boolean) : false);
  const importKinds = $derived(telRows.filter((row) => row.instructions.length || row.importPill)
    .map((row) => t(`transfer.restore.res.import_kind.${row.kind}`)));

  // Pliki: jeden wiersz zbiorczy; szczegóły (jak dotąd w podsumowaniu) pod „Szczegóły ▾”.
  const GROUP_NAME = (g: string) => t(`transfer.restore.group.${g.startsWith('other') ? 'others' : g}`);
  const filesPresent = $derived(done ? done.files_done + done.files_exists : 0);
  const filesBad = $derived(done ? done.files_denied + done.files_failed + done.files_missing : 0);
  const filesIncomplete = $derived(done ? done.status === 'incomplete' && filesBad === 0 : false);
  const filesRow = $derived.by(() => {
    if (!done) return null;
    const result = outcome === 'stopped' ? { text: num(filesPresent), tone: 'warn' as const }
      : filesBad > 0 ? { text: ofText(filesPresent, filesPresent + filesBad), tone: 'warn' as const }
      : { text: `✓ ${num(filesPresent)}`, tone: 'ok' as const };
    const names = [...new Set(r.choice.groups.map(GROUP_NAME))].join(' · ');
    const note = done.media_scan === 'restart' ? t('transfer.restore.restart') : done.media_scan === 'failed' ? t('transfer.restore.issue.scan') : '';
    return { result, sub: [names, note].filter(Boolean).join(' · ') || undefined };
  });
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

  // Aplikacje: nieudane z powodami w linii wiersza, cała lista pod „Lista ▾”, blokada Xiaomi jako etykieta.
  const why = (row: AppsResultRow) => t(`transfer.restore.apps_why.${row.status === 'pending' ? 'pending'
    : row.reason && APP_WHY.includes(row.reason) ? row.reason : 'failed'}`);
  const blockedRows = $derived((apps?.rows ?? []).filter((x) => x.status === 'skipped' && x.reason === 'user_restricted'));
  const problemRows = $derived((apps?.rows ?? []).filter((x) => x.status === 'failed' || x.status === 'pending'
    || (x.status === 'skipped' && x.reason !== 'user_restricted')));
  const appsLine = $derived.by(() => {
    const items = problemRows.slice(0, APP_LISTED).map((x) => t('transfer.restore.apps_skip_item', { name: x.label, reason: why(x) }));
    if (problemRows.length > APP_LISTED) items.push(t('transfer.restore.apps_skip_more', { count: num(problemRows.length - APP_LISTED) }));
    return items.join(' · ');
  });
  const appsRow = $derived.by(() => {
    if (apps) {
      const got = apps.installed + apps.exists;
      if (reinstalling) {
        return { result: { text: ap ? ofText(ap.done, ap.total) : '…', tone: 'mut' as Tone }, sub: t('transfer.restore.res.apps_running') };
      }
      const bad = problemRows.length + blockedRows.length > 0 || apps.stopped || !!appsError;
      return { result: bad ? { text: ofText(got, apps.selected), tone: 'warn' as Tone } : { text: `✓ ${num(got)}`, tone: 'ok' as Tone },
        sub: [appsLine, appsError ? errorText(appsError) : ''].filter(Boolean).join(' · ') || undefined };
    }
    if (appsError) return { result: { text: t('transfer.restore.res.not_written'), tone: 'bad' as Tone }, sub: errorText(appsError) };
    return null;
  });
  const appsMark = $derived.by((): StageMark | null => {
    if (!appsRow) return null;
    if (appsError) return { key: 'apps', tone: 'warn', note: t('transfer.restore.res.stage_note.error') };
    if (problemRows.length) return { key: 'apps', tone: 'warn', note: t('transfer.restore.res.stage_note.failed', { count: num(problemRows.length) }) };
    if (blockedRows.length && !gaveUp) return { key: 'apps', tone: 'warn', note: t(`transfer.restore.res.stage_note.${reinstalling ? 'installing' : 'blocked'}`) };
    return { key: 'apps', tone: 'ok' };
  });
  const appList = $derived((apps?.rows ?? []).map((x) => ({ ...x,
    state: x.status === 'installed' ? t('transfer.restore.apps_state.installed') : x.status === 'exists' ? t('transfer.restore.apps_state.exists')
      : why(x), ok: x.status === 'installed' || x.status === 'exists' })));
  let appsOpen = $state(false);
  let howOpen = $state(false);
  function toggleHow() {
    howOpen = !howOpen;
    if (howOpen) appsOpen = true;
  }

  // Etapy w prawym panelu: ✓ / ! z krótką notką; kolejność jak w postępie.
  const marks = $derived.by((): StageMark[] => {
    if (!done) return [];
    const list: StageMark[] = [];
    if (showFiles && filesRow) {
      const gallery = done?.media_scan === 'restart' || done?.media_scan === 'failed';
      list.push({ key: 'files', tone: filesRow.result.tone === 'ok' && !gallery && !filesIncomplete ? 'ok' : 'warn',
        note: outcome === 'stopped' ? t('transfer.restore.res.stage_note.stopped') : filesBad > 0 ? t('transfer.restore.res.stage_note.failed', { count: num(filesBad) })
          : gallery ? t('transfer.restore.res.stage_note.gallery') : filesIncomplete ? t('transfer.restore.res.stage_note.incomplete') : undefined });
    }
    if (tel && Object.keys(tel.safety).length) list.push({ key: 'safety', tone: safetyFailed ? 'warn' : 'ok', note: safetyFailed ? t('transfer.restore.res.stage_note.safety') : undefined });
    list.push(...telRows.map((row) => row.mark));
    if (telError) list.push({ key: 'messages', tone: 'warn', note: t('transfer.restore.res.stage_note.error') });
    if (appsMark) list.push(appsMark);
    return list;
  });

  // Jeden wynik u góry: zielony, żółty z powodem w jednym zdaniu albo czerwony (telefon nie wrócił do ustawień).
  const issues = $derived.by((): string[] => {
    if (!done) return [];
    const list: string[] = [];
    if (filesBad > 0) list.push(tp('transfer.restore.issue.files', filesBad, { count: num(filesBad) }));
    if (filesIncomplete) list.push(t('transfer.restore.issue.files_incomplete'));
    if (done.media_scan === 'failed') list.push(t('transfer.restore.issue.scan'));
    if (done.media_scan === 'restart') list.push(t('transfer.restore.restart'));
    if (telError) list.push(t('transfer.restore.issue.tel_error'));
    if (telFailed) list.push(t('transfer.restore.issue.tel_failed'));
    if (telRows.some((row) => row.visible)) list.push(t('transfer.restore.tel.visible'));
    if (safetyFailed) list.push(t('transfer.restore.issue.safety'));
    if (importKinds.length) list.push(t('transfer.restore.issue.import', { list: importKinds.join(', ') }));
    if (problemRows.length) list.push(tp('transfer.restore.issue.apps', problemRows.length, { count: num(problemRows.length) }));
    if (blockedRows.length && !gaveUp) list.push(t(`transfer.restore.issue.${reinstalling ? 'installing' : 'blocked'}`));
    if (appsError) list.push(t('transfer.restore.issue.apps_error'));
    return list;
  });
  const hero = $derived.by((): { tone: 'ok' | 'warn' | 'bad'; icon: 'check' | 'pause' | 'triangle-alert'; title: string; text?: string; sub?: string } | null => {
    if (!done) return null;
    if (telState === 'error') {
      return { tone: 'bad', icon: 'triangle-alert', title: t('transfer.restore.cleanup.failed'),
        text: t('transfer.restore.cleanup.failed_text', { app: smsAppName(r.tapPackage) }) };
    }
    if (outcome === 'stopped') {
      return { tone: 'warn', icon: 'pause', title: t('transfer.restore.done_stopped'), text: t('transfer.restore.done_stopped_text') };
    }
    const sub = t('transfer.restore.done_took', { size: size(done.bytes), time: took(done.seconds) });
    if (issues.length === 0) return { tone: 'ok', icon: 'check', title: t('transfer.restore.done_all'), sub };
    const line = issues.join(', ');
    return { tone: 'warn', icon: 'triangle-alert', title: t('transfer.restore.done_almost'), text: `${line.charAt(0).toLocaleUpperCase()}${line.slice(1)}.`, sub };
  });

  // Prawy panel
  const orderLine = $derived([r.order, s.client.trim() || r.copy?.client].filter(Boolean).join(' · '));
  const reported = $derived(r.order ? !!s.reports[r.order] : false);

  // Ramka WhatsApp (spec §6.1): tekst zależy od tego, czy aplikacja jest na telefonie.
  const wa = $derived(done ? r.whatsapp : null);
  const waApp = $derived.by(() => {
    if (!wa) return null;
    // aplikacja doinstalowana po odblokowaniu Xiaomi jest już „zainstalowana”
    const got = (apps?.rows ?? []).some((x) => WHATSAPP_PACKAGES.includes(x.package) && x.status === 'installed');
    return wa.app === 'missing' && got ? 'installed' : wa.app;
  });

  // Blokada Xiaomi w wyniku: program sam co RECHECK_MS pyta telefon (cichy odczyt) i po odblokowaniu raz dokańcza aplikacje.
  $effect(() => {
    const stop = recheck(() => ctl.reinstallWhenUnblocked(),
      () => s.phase === 'transfer_restored' && !!r.appsResult?.blocked && !r.reinstallDone && s.job === null);
    return stop;
  });
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-4 scroll-fade overflow-auto px-7 py-7">
    <div>
      <div class="text-sm font-semibold text-soft">{crumb}</div>
      <h1 class="text-2xl font-extrabold">{done ? t(outcome === 'stopped' ? 'transfer.restore.done_heading_stopped' : 'transfer.restore.done_heading') : t('transfer.restore.uploading')}</h1>
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
          {#if ap}
            <div class="text-sm text-mut">{ofText(ap.done, ap.total)}</div>
            {#if ap.current}<div class="truncate text-sm text-soft" title={ap.current}>{ap.current}</div>{/if}
            <p class="text-sm font-semibold text-mut">{t('transfer.restore.apps_consent')}</p>
          {:else if tp_}
            {#if tp_.kind !== 'safety'}
              <div class="text-sm text-mut">{ofText(tp_.done, tp_.total)}</div>
            {/if}
          {:else if p && p.total_files > 0}
            <div class="flex flex-wrap justify-between gap-2 text-sm text-mut">
              <span>{tp('transfer.progress_files', p.total_files, { done: num(p.done_files), count: num(p.total_files) })}</span>
              {#if p.total_bytes > 0}<span>{t('transfer.progress_size', { done: size(p.done_bytes), total: size(p.total_bytes) })}</span>{/if}
            </div>
          {/if}
          {#if !tp_ && !ap && p?.current}<div class="mono truncate text-xs text-soft" title={p.current}>{p.current}</div>{/if}
        </div>
      </Card>
      <TapPrompt />
      <div>
        <Button disabled={s.stopping || s.job?.kind !== 'restore'} onclick={() => ctl.stopRestore()}>
          {s.stopping ? t('transfer.stopping') : t('transfer.stop')}
        </Button>
      </div>
    {:else}
      <!-- jeden wynik: zielony, żółty z powodem w jednym zdaniu albo czerwony -->
      {#if hero}
        <div role={hero.tone === 'bad' ? 'alert' : 'status'} class="flex items-center gap-3.5 rounded-2xl border px-4 py-3.5
          {hero.tone === 'ok' ? 'border-ok/30 bg-ok-soft' : hero.tone === 'bad' ? 'border-bad/40 bg-bad-soft' : 'border-warn-strong/40 bg-warn-soft'}">
          <span class="grid h-9 w-9 flex-none place-items-center rounded-full
            {hero.tone === 'ok' ? 'bg-ok/15 text-ok' : hero.tone === 'bad' ? 'bg-bad/15 text-bad' : 'bg-warn-strong/25 text-warn'}">
            <Icon name={hero.icon} size={18} />
          </span>
          <div class="min-w-0 flex-1">
            <b class="block text-ink">{hero.title}</b>
            {#if hero.text}<span class={hero.tone === 'bad' ? 'text-bad' : 'text-warn'}>{hero.text}</span>{/if}
            {#if hero.sub}<span class="block text-sm {hero.tone === 'ok' ? 'text-ok' : 'text-warn'}">{hero.sub}</span>{/if}
          </div>
        </div>
      {/if}

      <CategoryGroup title={t('transfer.restore.res.card')} bare>
        {#each telRows as row (row.kind)}
          {#snippet pills()}{#if row.importPill}<Pill tone="warn">{t('transfer.restore.res.to_import')}</Pill>{/if}{/snippet}
          {#if row.details.length && row.instructions.length}
            <CategoryRow icon={row.icon} name={row.name} sub={row.sub} result={row.result} {pills} foldText={t('transfer.restore.res.details')} foldLabel={row.name}>
              {#snippet fold()}{@render lines(row.details)}{/snippet}
              {#snippet note()}{@render steps(row.instructions)}{/snippet}
            </CategoryRow>
          {:else if row.details.length}
            <CategoryRow icon={row.icon} name={row.name} sub={row.sub} result={row.result} {pills} foldText={t('transfer.restore.res.details')} foldLabel={row.name}>
              {#snippet fold()}{@render lines(row.details)}{/snippet}
            </CategoryRow>
          {:else if row.instructions.length}
            <CategoryRow icon={row.icon} name={row.name} sub={row.sub} result={row.result} {pills}>
              {#snippet note()}{@render steps(row.instructions)}{/snippet}
            </CategoryRow>
          {:else}
            <CategoryRow icon={row.icon} name={row.name} sub={row.sub} result={row.result} {pills} />
          {/if}
        {/each}
        {#if telErrorText}
          <CategoryRow icon={MessageSquare} name={t('transfer.group.messages')} sub={telErrorText}
            result={{ text: t('transfer.restore.res.not_written'), tone: 'bad' }} />
        {/if}
        {#if showFiles && filesRow}
          <CategoryRow icon={ImageIcon} name={t('transfer.restore.res.files')} sub={filesRow.sub} result={filesRow.result}
            fold={filesFold} foldText={t('transfer.restore.res.details')} foldLabel={t('transfer.restore.res.files')} />
        {/if}
        {#if appsRow}
          <CategoryRow icon={LayoutGrid} name={t('transfer.row.apps')} sub={appsRow.sub} result={appsRow.result}
            tone={apps?.blocked && !reinstalling && !gaveUp ? 'block' : null}
            fold={appList.length ? appsFold : undefined} foldText={t('transfer.restore.res.list')} foldLabel={t('transfer.row.apps')}
            foldOpen={appsOpen} onfold={(open) => (appsOpen = open)}>
            {#snippet pills()}
              {#if apps?.blocked && !reinstalling && !gaveUp}
                <button type="button" aria-expanded={howOpen} aria-controls="xiaomi-how" onclick={toggleHow}
                  class="inline-flex cursor-pointer items-center rounded-full bg-warn-soft px-2.5 py-0.5 text-xs font-bold whitespace-nowrap text-warn ring-1 ring-current/15 ring-inset hover:underline">
                  {t('transfer.restore.xiaomi_label')}
                </button>
              {/if}
            {/snippet}
          </CategoryRow>
        {/if}
      </CategoryGroup>

      {#if wa}
        <!-- opcjonalnie, z klientem: ramka przerywana, żeby nie wyglądała na wymóg -->
        <section aria-label={t('transfer.restore.wa.title')} class="rounded-2xl border border-dashed border-line px-4 py-3">
          <div class="flex items-start gap-3">
            <span class="grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] bg-accent-soft text-accent" aria-hidden="true">
              <MessageCircle size={16} strokeWidth={2} aria-hidden="true" />
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-bold text-ink">{t('transfer.restore.wa.title')}</span>
                <Pill tone="neutral">{t('transfer.restore.wa.optional')}</Pill>
              </div>
              <p class="text-[12.5px] leading-snug text-mut">{t(`transfer.restore.wa.${waApp === 'missing' ? 'missing' : 'installed'}`)}</p>
              {#if waApp === 'pre_installed'}<p class="text-[12.5px] leading-snug text-mut">{t('transfer.restore.wa.pre_installed')}</p>{/if}
              {#if r.order}
                <label class="flex w-fit cursor-pointer items-center gap-2 text-sm font-semibold text-ink">
                  <input type="checkbox" class="h-[17px] w-[17px] accent-accent" checked={r.whatsappRestored}
                    onchange={(e) => ctl.setWhatsappRestored(e.currentTarget.checked)} />
                  {t('transfer.restore.wa.check')}
                </label>
              {/if}
            </div>
          </div>
        </section>
      {/if}
    {/if}
  </main>

  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.device?.serial ?? s.serial ?? ''} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected={!s.transfer.waiting} />
    {#if done}
      {#if orderLine}<div class="text-sm text-mut">{orderLine}</div>{/if}
      {#if marks.length}
        <div class="lbl mt-1">{t('transfer.restore.res.stages')}</div>
        <ol aria-label={t('transfer.restore.stages_label')} class="flex flex-col gap-2 text-sm">
          {#each marks as m (m.key)}
            <li data-state={m.tone} class="flex items-start gap-2 {m.tone === 'ok' ? 'text-mut' : 'font-semibold text-ink'}">
              <span aria-hidden="true" class="mt-px grid h-[18px] w-[18px] flex-none place-items-center rounded-full text-[11px] font-extrabold text-white
                {m.tone === 'ok' ? 'bg-ok' : "bg-warn-strong before:content-['!']"}">
                {#if m.tone === 'ok'}<Check size={11} strokeWidth={3} />{/if}
              </span>
              <span class="sr-only">{m.tone === 'ok' ? t('transfer.stage_done') : t('transfer.restore.res.stage_warn')}</span>
              <span class="min-w-0">{t(`transfer.restore.stage.${m.key}`)}{#if m.note}{' — '}{m.note}{/if}</span>
            </li>
          {/each}
        </ol>
      {/if}
      <div class="mt-1 flex flex-col gap-2 border-t border-line pt-3.5">
        {#if r.order}
          <ReportButton order={r.order} variant="primary" size="lg" label={t('transfer.restore.res.protocol')} hint={t('transfer.restore.res.protocol_hint')} />
          <Button onclick={() => ctl.leaveTransfer()}>{reported ? t('transfer.finish') : t('transfer.restore.res.finish_no_report')}</Button>
        {:else}
          <Button variant="primary" onclick={() => ctl.leaveTransfer()}>{t('transfer.finish')}</Button>
        {/if}
      </div>
    {/if}
  </SidePanel>
</div>

{#snippet lines(items: string[])}
  <ul class="flex flex-col gap-1">
    {#each items as line (line)}<li>{line}</li>{/each}
  </ul>
{/snippet}

<!-- krok do zrobienia na telefonie: widoczny od razu, bo bez niego dane nie są kompletne -->
{#snippet steps(items: string[])}
  <div class="flex flex-col gap-1">
    {#each items as line (line)}<p><b class="text-ink">{t('transfer.restore.res.on_phone')}</b> {line}</p>{/each}
  </div>
{/snippet}

<!-- Pliki: dawne podsumowanie, teraz pod „Szczegóły ▾” -->
{#snippet filesFold()}
  {#if done}
    <div class="flex flex-col gap-2">
      <dl class="grid max-w-md grid-cols-[1fr_auto] gap-x-6 gap-y-1">
        <dt>{t('transfer.restore.sum.done')}</dt><dd class="text-right font-bold text-ink">{num(done.files_done)}</dd>
        <dt>{t('transfer.restore.sum.exists')}</dt><dd class="text-right font-bold text-ink">{num(done.files_exists)}</dd>
        <dt>{t('transfer.restore.sum.size')}</dt><dd class="text-right font-bold text-ink">{size(done.bytes)}</dd>
        <dt>{t('transfer.restore.sum.checked')}</dt>
        <dd class="text-right font-bold text-ink">{t(done.hashed ? 'transfer.restore.sum.checked_hash' : 'transfer.restore.sum.checked_size')}</dd>
      </dl>
      {#if notes.length}
        <ul class="flex flex-col gap-1">
          {#each notes as n (n.text)}<li class={n.warn ? 'font-semibold text-warn' : ''}>{n.text}</li>{/each}
        </ul>
      {/if}
    </div>
  {/if}
{/snippet}

<!-- Aplikacje: cała lista; instrukcja Xiaomi tylko po kliknięciu etykiety -->
{#snippet appsFold()}
  <div class="flex flex-col gap-2.5">
    {#if apps?.blocked && howOpen && !reinstalling && !gaveUp}
      <p id="xiaomi-how" class="rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-warn">{t('transfer.restore.xiaomi_how_done')}</p>
    {/if}
    <ul class="grid max-h-72 grid-cols-2 gap-x-6 gap-y-1.5 overflow-auto pr-1">
      {#each appList as a (a.package)}
        <li class="flex min-w-0 items-baseline gap-2">
          <span class="min-w-0 flex-1 truncate text-ink" title={a.package}>{a.label}</span>
          <span class="flex-none text-xs {a.ok ? 'text-soft' : 'text-warn'}">{a.state}</span>
        </li>
      {/each}
    </ul>
  </div>
{/snippet}
