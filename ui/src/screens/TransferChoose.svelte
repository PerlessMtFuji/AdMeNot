<script lang="ts">
  import Download from '@lucide/svelte/icons/download';
  import Folder from '@lucide/svelte/icons/folder';
  import ImageIcon from '@lucide/svelte/icons/image';
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
  import MessageCircle from '@lucide/svelte/icons/message-circle';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import PhoneIcon from '@lucide/svelte/icons/phone';
  import Users from '@lucide/svelte/icons/users';
  import { getContext, type Snippet } from 'svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { EXPORT_KINDS, exportFiles, formatSize, isXiaomi, modelName, transferNeed, transferTotals, whatsappStale } from '../lib/logic';
  import type { ExportKind } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Row = { key: string; icon: typeof Users; title: string; meta: string; note?: string; bytes: number | null;
    checked: boolean; disabled: boolean; kind?: ExportKind };

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const inv = $derived(s.transfer.inventory);
  const sel = $derived(s.transfer.selection);
  const totals = $derived(inv ? transferTotals(inv, sel) : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const nothing = $derived(!totals || totals.categories === 0);
  // Przy wznowieniu wolne miejsce zmalało już o skopiowaną część — porównujemy tylko resztę.
  const noSpace = $derived(!!inv && !!totals && transferNeed(totals.bytes, s.transfer.resumable) > inv.free_pc);
  const blocked = $derived(nothing || noSpace || s.job !== null);
  const serial = $derived(s.device?.serial ?? s.serial ?? '');
  let listOpen = $state(false);

  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const readable = (n: number | null) => n !== null && n > 0;
  const count = (n: number | null, key: string) => (n === null ? t('transfer.unavailable') : tp(key, n, { count: num(n) }));

  // Kategorie telefonu, których nie dało się odczytać: odmowa telefonu (`denied`) albo zwykły błąd odczytu.
  // Dla nich most szuka plików eksportu; wybrany plik zastępuje odczyt z telefonu.
  const files = (k: ExportKind) => (inv ? exportFiles(inv, k) : []);
  const chosen = (k: ExportKind) => files(k).find((f) => f.remote === sel.exports?.[k]) ?? null;
  const rowOn = (k: ExportKind) => (k === 'sms' ? sel.sms || sel.mms : sel[k]);
  function fileMeta(k: ExportKind): string {
    const f = chosen(k);
    if (!f) return t('transfer.unavailable');
    return f.count === null ? t('transfer.export.from_file') : tp('transfer.export.count', f.count, { count: num(f.count) });
  }
  const problems = $derived(inv ? EXPORT_KINDS.filter((k) => (k === 'sms' ? inv.sms === null || inv.mms === null : inv[k] === null)) : []);
  const deniedKinds = $derived(problems.filter((k) => inv?.denied?.includes(k)));
  const rescanning = $derived(s.job?.kind === 'transfer_scan');
  /** „kontaktów”, „kontaktów i wiadomości”, „kontaktów, wiadomości i historii połączeń”. */
  function what(kinds: ExportKind[]): string {
    const w = kinds.map((k) => t(`transfer.export.what.${k}`));
    return w.length < 2 ? w.join('') : w.slice(0, -1).join(t('transfer.export.what.sep')) + t('transfer.export.what.and') + w.at(-1);
  }
  // Czas pliku spoza zakresu dat (most daje null): bez daty zamiast „Invalid Date”.
  const fileDate = (iso: string | null) => iso === null ? '' : new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  const phoneRows = $derived.by((): Row[] => {
    if (!inv) return [];
    const messages = inv.sms === null && inv.mms === null ? null : (inv.sms ?? 0) + (inv.mms ?? 0);
    const smsFile = !readable(inv.sms) && !readable(inv.mms) ? chosen('sms') : null;
    return [
      { key: 'contacts', icon: Users, title: t('transfer.row.contacts'), meta: inv.contacts === null ? fileMeta('contacts') : num(inv.contacts),
        note: chosen('contacts') ? undefined : t('transfer.row.contacts_note'), bytes: null, checked: sel.contacts,
        disabled: !readable(inv.contacts) && !files('contacts').length, kind: 'contacts' },
      { key: 'sms', icon: MessageSquare, title: t('transfer.row.sms'),
        meta: messages === null ? fileMeta('sms') : count(messages, 'transfer.messages'),
        note: smsFile ? undefined : t('transfer.row.sms_note'), bytes: readable(inv.mms) ? inv.mms_bytes : null, checked: sel.sms || sel.mms,
        disabled: !readable(inv.sms) && !readable(inv.mms) && !files('sms').length, kind: 'sms' },
      { key: 'calls', icon: PhoneIcon, title: t('transfer.row.calls'), meta: inv.calls === null ? fileMeta('calls') : num(inv.calls),
        bytes: null, checked: sel.calls, disabled: !readable(inv.calls) && !files('calls').length, kind: 'calls' },
    ];
  });

  function fileRow(key: 'media' | 'downloads' | 'whatsapp', icon: typeof Users, note: string): Row {
    const c = inv!.categories[key];
    return { key, icon, title: t(`transfer.row.${key}`), meta: tp('transfer.files', c.files, { count: num(c.files) }), note,
      bytes: c.bytes, checked: sel.categories.includes(key), disabled: c.files === 0 };
  }
  const othersBytes = $derived(inv?.others.reduce((n, o) => n + o.bytes, 0) ?? 0);
  // Rozmiar zaznaczonych aplikacji; pusto, gdy telefon nie dał odczytać żadnego rozmiaru APK.
  const appsBytes = $derived(inv?.apps.some((a) => a.bytes !== null)
    ? inv.apps.filter((a) => sel.apps.includes(a.package)).reduce((n, a) => n + (a.bytes ?? 0), 0) : null);
  const suspicious = $derived(inv?.apps.filter((a) => a.verdict === 'suspicious').length ?? 0);
  const waOld = $derived(!!inv && inv.categories.whatsapp.files > 0 && whatsappStale(inv.whatsapp_backup, new Date()));
  let waChecking = $state(false);
  async function recheckWhatsapp() {
    waChecking = true;
    try { await ctl.recheckWhatsapp(); } finally { waChecking = false; }
  }
</script>

{#snippet row(r: Row, extra?: Snippet)}
  <div class="rounded-2xl card px-4 py-3 transition-opacity duration-150 {r.checked ? '' : 'opacity-70'}">
    <div class="flex items-start gap-3.5">
      <label class="flex min-w-0 flex-1 items-start gap-3.5 {r.disabled ? '' : 'cursor-pointer'}">
        <input type="checkbox" class="mt-2.5 h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={r.checked}
          disabled={r.disabled} onchange={() => ctl.toggleTransfer(r.key)} />
        <span class="grid h-9 w-9 flex-none place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true"><r.icon size={18} /></span>
        <span class="min-w-0 flex-1">
          <span class="block font-bold">{r.title} <span class="ml-1 text-sm font-semibold text-soft">{r.meta}</span></span>
          <!-- przy problemie z odczytem podpowiedź wiersza ustępuje komunikatowi pod nim -->
          {#if r.note && !(r.kind && problems.includes(r.kind))}<span class="block text-sm text-mut">{r.note}</span>{/if}
        </span>
      </label>
      <span class="mono flex-none pt-1.5 text-sm text-mut">{r.bytes !== null ? size(r.bytes) : ''}</span>
    </div>
    {#if r.kind && problems.includes(r.kind)}<div class="mt-1.5 pl-[82px]">{@render exportNote(r.kind)}</div>{/if}
    {#if extra}<div class="mt-2 pl-[76px]">{@render extra()}</div>{/if}
  </div>
{/snippet}

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-3 scroll-fade overflow-auto px-7 py-7">
    <div class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <div class="text-sm font-semibold text-soft">{crumb}</div>
        <h1 class="text-2xl font-extrabold">{inv ? t('transfer.title') : t('transfer.reading')}</h1>
        <p class="text-mut">{inv ? t('transfer.sub') : t('transfer.reading_sub')}</p>
      </div>
      <Button variant="ghost" size="sm" onclick={() => ctl.leaveTransfer()}><Icon name="arrow-left" size={14} />{t('common.back')}</Button>
    </div>

    {#if !inv}
      <div class="flex items-center gap-2 font-semibold text-mut"><Spinner />{t('transfer.reading')}</div>
    {:else}
      {#if s.transfer.resumable}
        {@const r = s.transfer.resumable}
        <Banner tone="info" icon="rotate-ccw" title={t('transfer.resume_title', { when: when(r.created) })}>
          {t('transfer.resume_text')}
          {#snippet actions()}
            <Button variant="primary" size="sm" disabled={blocked} onclick={() => ctl.startBackup()}>{t('transfer.resume')}</Button>
          {/snippet}
        </Banner>
      {/if}

      <span class="lbl mt-1">{t('transfer.group.phone')}</span>
      {#each phoneRows as r (r.key)}{@render row(r)}{/each}

      <span class="lbl mt-2">{t('transfer.group.files')}</span>
      {#if inv.unreadable > 0}
        <Banner tone="warn" icon="triangle-alert" title={tp('transfer.unreadable_files', inv.unreadable, { count: num(inv.unreadable) })}>
          {t('transfer.unreadable_files_text')}
        </Banner>
      {/if}

      {@render row(fileRow('media', ImageIcon, t('transfer.row.media_note')))}
      {@render row(fileRow('downloads', Download, t('transfer.row.downloads_note')))}
      {@render row(fileRow('whatsapp', MessageCircle, t('transfer.row.whatsapp_note')), waOld ? whatsapp : undefined)}
      {@render row({ key: 'others', icon: Folder, title: t('transfer.row.others'),
        meta: tp('transfer.folders', inv.others.length, { count: num(inv.others.length) }), bytes: othersBytes,
        checked: sel.others.length > 0, disabled: inv.others.length === 0 }, inv.others.length ? others : undefined)}

      <span class="lbl mt-2">{t('transfer.group.apps')}</span>
      {@render row({ key: 'apps', icon: LayoutGrid, title: t('transfer.row.apps'), meta: num(inv.apps.length),
        note: t('transfer.row.apps_note'), bytes: appsBytes, checked: sel.apps.length > 0, disabled: inv.apps.length === 0 }, apps)}
    {/if}
  </main>

  <SidePanel label={t('transfer.panel')}>
    <DeviceCard compact name={name} {serial} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected />
    {#if inv && totals}
      <span class="lbl mt-2">{t('transfer.panel')}</span>
      <dl class="flex flex-col gap-1.5 text-sm">
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.size')}</dt><dd class="font-bold" data-testid="transfer-size">{size(totals.bytes)}</dd></div>
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.eta')}</dt><dd class="font-bold">{t('transfer.eta_value', { min: totals.etaMin })}</dd></div>
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.free')}</dt><dd class="font-bold">{size(inv.free_pc)}</dd></div>
      </dl>
      {#if noSpace}<Banner tone="warn" icon="triangle-alert" title={t('transfer.no_space')} />{/if}
      <div class="flex items-start gap-2.5 rounded-xl bg-neutral-soft p-3 text-sm text-mut">
        <span class="mt-0.5 flex-none text-soft"><Icon name="lock" size={15} /></span><span>{t('transfer.privacy', { days: s.settings.transfer_keep_days })}</span>
      </div>
      <Button variant="primary" size="lg" class="flex-col !gap-0" disabled={blocked} onclick={() => ctl.startBackup()}>
        {t('transfer.begin')}
        <small class="text-xs font-semibold opacity-85">{tp('transfer.categories', totals.categories)} · {size(totals.bytes)}</small>
      </Button>
    {/if}
  </SidePanel>
</div>

{#snippet inlineNote(text: string)}
  <p class="flex items-start gap-1.5 text-sm font-semibold text-warn">
    <span class="mt-0.5 flex-none" aria-hidden="true"><Icon name="triangle-alert" size={14} /></span><span>{text}</span>
  </p>
{/snippet}

{#snippet exportNote(k: ExportKind)}
  {@const list = files(k)}
  {@const denied = deniedKinds.includes(k)}
  {@const xiaomi = denied && isXiaomi(s.device)}
  <div class="flex flex-col gap-1.5" data-testid="export-note-{k}">
    {@render inlineNote(denied
      ? t(chosen(k) && rowOn(k) ? 'transfer.export.title_denied_file' : 'transfer.export.title_denied', { what: what([k]) })
      : t('transfer.export.title_failed', { what: what([k]) }))}
    <div class="flex flex-col gap-1.5 pl-5 text-sm text-mut">
      {#if list.length}
        {@render exportList(k)}
        <details class="group">
          <summary class="w-fit cursor-pointer font-semibold text-accent hover:underline">{t('transfer.export.howto_toggle')}</summary>
          {@render howto(k, xiaomi)}
        </details>
      {:else}
        {@render howto(k, xiaomi)}
      {/if}
      {@render recheck(() => ctl.rescanTransfer(), s.job !== null, rescanning)}
    </div>
  </div>
{/snippet}

<!-- Instrukcja tylko dla danych z tego wiersza: kontakty to .vcf z aplikacji Kontakty, SMS i połączenia — SMS Backup & Restore. -->
{#snippet howto(k: ExportKind, xiaomi: boolean)}
  <div class="mt-1 flex flex-col gap-1">
    {#if xiaomi}<p>{t('transfer.export.xiaomi')}</p>{/if}
    <p>{t(xiaomi ? 'transfer.export.howto' : 'transfer.export.howto_plain', { steps: t(`transfer.export.steps.${k}`) })}</p>
  </div>
{/snippet}

<!-- „Sprawdź ponownie” pod komunikatem w wierszu: ten sam wygląd przy plikach eksportu i kopii czatów WhatsApp. -->
{#snippet recheck(onclick: () => void, disabled: boolean, busy: boolean)}
  <button type="button" class="flex w-fit items-center gap-1.5 font-semibold text-accent hover:underline disabled:cursor-default disabled:text-soft disabled:no-underline"
    {disabled} {onclick}>
    {#if busy}<Spinner />{:else}<Icon name="rotate-ccw" size={13} />{/if}{t('transfer.recheck')}
  </button>
{/snippet}

{#snippet exportList(k: ExportKind)}
  <div role="radiogroup" id="export-files-{k}" aria-label={`${t('transfer.export.files')} · ${t(`transfer.row.${k}`)}`} class="flex flex-col gap-0.5">
    {#each files(k) as f, i (f.remote)}
      <label class="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-ink
        {i === 0 ? 'bg-accent-soft shadow-[inset_3px_0_0_var(--color-accent)]' : 'opacity-75'}">
        <input type="radio" name="export-{k}" class="h-4 w-4 flex-none accent-[var(--color-accent)]"
          checked={sel.exports?.[k] === f.remote} onchange={() => ctl.chooseExport(k, f.remote)} />
        <span class="mono min-w-0 flex-1 truncate text-xs" title={f.remote}>{f.name}</span>
        <span class="whitespace-nowrap text-mut">{fileDate(f.mtime)}</span>
        <span class="w-28 whitespace-nowrap text-right text-mut">
          {f.count === null ? size(f.size) : tp(`transfer.export.items.${k}`, f.count, { count: num(f.count) })}
        </span>
        <span class="flex w-[84px] flex-none justify-end">{#if i === 0}<Pill tone="accent">{t('transfer.export.newest')}</Pill>{/if}</span>
      </label>
    {/each}
  </div>
{/snippet}

{#snippet whatsapp()}
  {@const backup = inv?.whatsapp_backup ?? null}
  <!-- jak komunikat o plikach eksportu: bez listy do wyboru instrukcja jest od razu widoczna, przycisk pod nią -->
  <div class="flex flex-col gap-1.5 pl-1.5" data-testid="whatsapp-note">
    {@render inlineNote(backup ? t('transfer.whatsapp_old_title', { when: when(backup) }) : t('transfer.whatsapp_none_title'))}
    <div class="flex flex-col gap-1.5 pl-5 text-sm text-mut">
      <p>{t('transfer.whatsapp_howto')}</p>
      {@render recheck(recheckWhatsapp, waChecking || s.job !== null, waChecking)}
    </div>
  </div>
{/snippet}

{#snippet others()}
  <div class="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
    {#each inv?.others ?? [] as o (o.name)}
      <label class="flex cursor-pointer items-center gap-2">
        <input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={sel.others.includes(o.name)}
          onchange={() => ctl.toggleTransferOther(o.name)} />
        <span>{o.name || t('transfer.row.root')} <span class="text-soft">· {size(o.bytes)}</span></span>
      </label>
    {/each}
  </div>
{/snippet}

{#snippet apps()}
  <div class="flex flex-wrap items-center gap-1.5">
    <Pill tone="ok">{t('transfer.apps_copy', { count: num(sel.apps.length) })}</Pill>
    {#if inv?.skipped_apps.length}<Pill tone="bad">{tp('transfer.apps_skipped', inv.skipped_apps.length)}</Pill>{/if}
    {#if suspicious}<Pill tone="warn">{tp('transfer.apps_suspicious', suspicious)}</Pill>{/if}
  </div>
  {#if inv?.apps.length}
    <button type="button" class="mt-1.5 text-sm font-semibold text-accent hover:underline" aria-expanded={listOpen}
      onclick={() => (listOpen = !listOpen)}>{listOpen ? t('transfer.hide_list') : t('transfer.show_list')}</button>
  {/if}
  {#if listOpen}
    <ul class="mt-1.5 flex flex-col gap-1 text-sm">
      {#each inv?.apps ?? [] as a (a.package)}
        <li>
          <label class="flex cursor-pointer items-center gap-2">
            <input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={sel.apps.includes(a.package)}
              onchange={() => ctl.toggleTransferApp(a.package)} />
            <span class="truncate">{a.label}</span>
            {#if a.label !== a.package}<span class="mono truncate text-2xs text-soft">{a.package}</span>{/if}
            {#if a.verdict === 'suspicious'}<Pill tone="warn">{t('transfer.suspicious')}</Pill>{/if}
            {#if a.bytes !== null}<span class="mono ml-auto flex-none text-2xs text-soft">{size(a.bytes)}</span>{/if}
          </label>
        </li>
      {/each}
    </ul>
  {/if}
{/snippet}
