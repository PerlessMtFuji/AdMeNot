<script lang="ts">
  import Download from '@lucide/svelte/icons/download';
  import Folder from '@lucide/svelte/icons/folder';
  import ImageIcon from '@lucide/svelte/icons/image';
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
  import MessageCircle from '@lucide/svelte/icons/message-circle';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import PhoneIcon from '@lucide/svelte/icons/phone';
  import Users from '@lucide/svelte/icons/users';
  import { getContext, type Component } from 'svelte';
  import CategoryGroup from '../components/transfer/CategoryGroup.svelte';
  import CategoryRow from '../components/transfer/CategoryRow.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { EXPORT_KINDS, exportFiles, formatSize, isXiaomi, modelName, transferNeed, transferTotals, whatsappStale } from '../lib/logic';
  import { recheck } from '../lib/recheck';
  import type { ExportKind } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Glyph = Component<{ size?: number; strokeWidth?: number; 'aria-hidden'?: 'true' }>;
  type Row = { key: string; icon: Glyph; name: string; count?: string; size?: string; checked: boolean; disabled: boolean;
    kind?: ExportKind };

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

  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const count = (n: number | null, key: string) => (n === null ? t('transfer.unavailable') : tp(key, n, { count: num(n) }));

  // Kategorie telefonu, których nie dało się odczytać: odmowa telefonu (`denied`) albo zwykły błąd odczytu.
  // Dla nich most szuka plików eksportu; wybrany plik zastępuje odczyt z telefonu.
  const files = (k: ExportKind) => (inv ? exportFiles(inv, k) : []);
  const chosen = (k: ExportKind) => files(k).find((f) => f.remote === sel.exports?.[k]) ?? null;
  function fileMeta(k: ExportKind): string {
    const f = chosen(k);
    if (!f) return '';  // bez pliku mówi o tym etykieta w wierszu („telefon nie pozwala odczytać”)
    return f.count === null ? t('transfer.export.from_file') : tp('transfer.export.count', f.count, { count: num(f.count) });
  }
  const problems = $derived(inv ? EXPORT_KINDS.filter((k) => (k === 'sms' ? inv.sms === null || inv.mms === null : inv[k] === null)) : []);
  const deniedKinds = $derived(problems.filter((k) => inv?.denied?.includes(k)));
  // Czas pliku spoza zakresu dat (most daje null): bez daty zamiast „Invalid Date”.
  const fileDate = (iso: string | null) => iso === null ? '' : new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  // Rozwinięcia sterowane stąd, bo od nich zależy automatyczne sprawdzanie telefonu.
  let opened = $state<Record<string, boolean>>({});
  const setOpen = (key: string) => (open: boolean) => { opened[key] = open; };
  const exportOpen = $derived(problems.some((k) => opened[k]));

  const positive = (n: number | null | undefined) => n !== null && n !== undefined && n > 0;

  const messageRows = $derived.by((): Row[] => {
    if (!inv) return [];
    const messages = inv.sms === null && inv.mms === null ? null : (inv.sms ?? 0) + (inv.mms ?? 0);
    const rows: Row[] = [
      { key: 'contacts', icon: Users, name: t('transfer.row.contacts'), count: inv.contacts === null ? fileMeta('contacts') || undefined : num(inv.contacts),
        checked: sel.contacts, disabled: !positive(inv.contacts) && !files('contacts').length, kind: 'contacts' },
      { key: 'sms', icon: MessageSquare, name: t('transfer.row.sms'),
        count: messages === null ? fileMeta('sms') || undefined : count(messages, 'transfer.messages'),
        size: positive(inv.mms) && inv.mms_bytes ? size(inv.mms_bytes) : undefined, checked: sel.sms || sel.mms,
        disabled: !positive(inv.sms) && !positive(inv.mms) && !files('sms').length, kind: 'sms' },
      { key: 'calls', icon: PhoneIcon, name: t('transfer.row.calls'), count: inv.calls === null ? fileMeta('calls') || undefined : num(inv.calls),
        checked: sel.calls, disabled: !positive(inv.calls) && !files('calls').length, kind: 'calls' },
    ];
    return rows;
  });
  // Pusta kategoria (odczytana, zero pozycji) nie dostaje wiersza, tylko szarą linię na dole grupy.
  const isEmpty = (r: Row) => r.disabled && !(r.kind && problems.includes(r.kind));
  const shownMessages = $derived(messageRows.filter((r) => !isEmpty(r)));

  const fileRows = $derived.by((): Row[] => {
    if (!inv) return [];
    const make = (key: 'media' | 'downloads' | 'whatsapp', icon: Glyph): Row => {
      const c = inv.categories[key];
      return { key, icon, name: t(`transfer.row.${key}`), count: num(c.files), size: size(c.bytes),
        checked: sel.categories.includes(key), disabled: c.files === 0 };
    };
    return [make('media', ImageIcon), make('downloads', Download), make('whatsapp', MessageCircle)];
  });
  const othersBytes = $derived(inv?.others.reduce((n, o) => n + o.bytes, 0) ?? 0);
  const emptyNames = (rows: Row[], extra: string[] = []) => [...rows.filter(isEmpty).map((r) => r.name), ...extra].join(', ');
  const filesEmpty = $derived(emptyNames(fileRows, inv && inv.others.length === 0 ? [t('transfer.row.others')] : []));
  const messagesEmpty = $derived(emptyNames(messageRows));
  // Rozmiar zaznaczonych aplikacji; pusto, gdy telefon nie dał odczytać żadnego rozmiaru APK.
  const appsBytes = $derived(inv?.apps.some((a) => a.bytes !== null)
    ? inv.apps.filter((a) => sel.apps.includes(a.package)).reduce((n, a) => n + (a.bytes ?? 0), 0) : null);
  const suspicious = $derived(inv?.apps.filter((a) => a.verdict === 'suspicious' && !sel.apps.includes(a.package)).length ?? 0);
  const waOld = $derived(!!inv && inv.categories.whatsapp.files > 0 && whatsappStale(inv.whatsapp_backup, new Date()));

  // Zamiast przycisków „Sprawdź ponownie”: gdy rozwinięcie z instrukcją jest otwarte, program sam co RECHECK_MS pyta
  // telefon. Eksport to tani odczyt (`transfer_exports_check`: liczby z providerów i pliki eksportu, bez zadania), WhatsApp — odczyt kopii czatów.
  // Nic nie idzie naraz: `recheck` czeka na koniec poprzedniego, a trwające zadanie na telefonie wstrzymuje oba sprawdzenia.
  $effect(() => {
    const stopExport = recheck(() => ctl.checkExports(), () => exportOpen && s.job === null);
    const stopWa = recheck(() => ctl.recheckWhatsapp(), () => !!opened.whatsapp && waOld && s.job === null);
    return () => { stopExport(); stopWa(); };
  });
</script>

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
      {#if inv.unreadable > 0}
        <Banner tone="warn" icon="triangle-alert" title={tp('transfer.unreadable_files', inv.unreadable, { count: num(inv.unreadable) })}>
          {t('transfer.unreadable_files_text')}
        </Banner>
      {/if}

      <CategoryGroup title={t('transfer.group.messages')} empty={messagesEmpty} missingKey="transfer.row.missing_phone">
        {#each shownMessages as r (r.key)}
          {@const k = r.kind!}
          {@const bad = problems.includes(k)}
          {@const blockedRow = bad && !chosen(k)}
          {#snippet exportFold()}{@render exportNote(k)}{/snippet}
          <CategoryRow icon={r.icon} name={r.name} count={r.count} size={r.size} checked={r.checked} disabled={r.disabled}
            ontoggle={() => ctl.toggleTransfer(r.key)} tone={blockedRow ? 'warn' : null}
            fold={bad ? exportFold : undefined} foldLabel={r.name} foldText={blockedRow ? t('transfer.row.how_copy') : t('transfer.row.export_files')}
            foldOpen={!!opened[r.key]} onfold={setOpen(r.key)}>
            {#snippet pills()}
              {#if blockedRow}<Pill tone="warn">{t(deniedKinds.includes(k) ? 'transfer.row.unreadable' : 'transfer.row.read_failed')}</Pill>{/if}
            {/snippet}
          </CategoryRow>
        {/each}
      </CategoryGroup>

      <CategoryGroup title={t('transfer.group.files')} empty={filesEmpty} missingKey="transfer.row.missing_phone">
        {#each fileRows.filter((r) => !isEmpty(r)) as r (r.key)}
          {@const wa = r.key === 'whatsapp' && waOld}
          <CategoryRow icon={r.icon} name={r.name} count={r.count} size={r.size} checked={r.checked} disabled={r.disabled}
            ontoggle={() => ctl.toggleTransfer(r.key)} tone={wa ? 'warn' : null}
            fold={wa ? whatsappFold : undefined} foldLabel={r.name} foldText={t('transfer.row.how_make')}
            foldOpen={!!opened[r.key]} onfold={setOpen(r.key)}>
            {#snippet pills()}
              {#if wa}<Pill tone="warn">{t('transfer.row.no_wa_backup')}</Pill>{/if}
            {/snippet}
          </CategoryRow>
        {/each}
        {#if inv.others.length}
          <CategoryRow icon={Folder} name={t('transfer.row.others')} count={num(inv.others.length)} size={size(othersBytes)}
            checked={sel.others.length > 0} ontoggle={() => ctl.toggleTransfer('others')} fold={othersFold} foldLabel={t('transfer.row.others')}
            foldOpen={!!opened.others} onfold={setOpen('others')} />
        {/if}
      </CategoryGroup>

      <CategoryGroup title={t('transfer.group.apps')} empty={inv.apps.length === 0 ? t('transfer.row.apps') : undefined}
        missingKey="transfer.row.missing_phone">
        {#if inv.apps.length}
          <CategoryRow icon={LayoutGrid} name={t('transfer.row.apps')} count={num(inv.apps.length)} sub={t('transfer.row.apps_note')}
            size={appsBytes !== null ? size(appsBytes) : undefined} checked={sel.apps.length > 0}
            ontoggle={() => ctl.toggleTransfer('apps')} fold={appsFold} foldLabel={t('transfer.row.apps')}
            foldOpen={!!opened.apps} onfold={setOpen('apps')}>
            {#snippet pills()}
              {#if inv.skipped_apps.length}<Pill tone="bad">{tp('transfer.apps_skipped', inv.skipped_apps.length)}</Pill>{/if}
              {#if suspicious}<Pill tone="warn">{tp('transfer.apps_suspicious', suspicious)}</Pill>{/if}
            {/snippet}
          </CategoryRow>
        {/if}
      </CategoryGroup>
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

{#snippet autoCheck(text: string)}
  <p class="mt-1 flex items-center gap-1.5 text-xs text-soft">{text}</p>
{/snippet}

<!-- Rozwinięcie wiersza z problemem odczytu: lista plików eksportu (jeśli są) i instrukcja eksportu. -->
{#snippet exportNote(k: ExportKind)}
  {@const list = files(k)}
  {@const xiaomi = deniedKinds.includes(k) && isXiaomi(s.device)}
  <div class="flex flex-col gap-1.5" data-testid="export-note-{k}">
    {#if list.length}
      {@render exportList(k)}
      <details class="group">
        <summary class="w-fit cursor-pointer font-semibold text-accent hover:underline">{t('transfer.export.howto_toggle')}</summary>
        {@render howto(k, xiaomi)}
      </details>
    {:else}
      {@render howto(k, xiaomi)}
    {/if}
    {@render autoCheck(t('transfer.auto_check_file'))}
  </div>
{/snippet}

<!-- Instrukcja tylko dla danych z tego wiersza: kontakty to .vcf z aplikacji Kontakty, SMS i połączenia — SMS Backup & Restore. -->
{#snippet howto(k: ExportKind, xiaomi: boolean)}
  <div class="mt-1 flex flex-col gap-1">
    {#if xiaomi}<p>{t('transfer.export.xiaomi')}</p>{/if}
    <p>{t(xiaomi ? 'transfer.export.howto' : 'transfer.export.howto_plain', { steps: t(`transfer.export.steps.${k}`) })}</p>
  </div>
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

{#snippet whatsappFold()}
  {@const backup = inv?.whatsapp_backup ?? null}
  <div class="flex flex-col gap-1" data-testid="whatsapp-note">
    {#if backup}<p>{t('transfer.whatsapp_old_title', { when: when(backup) })}</p>{/if}
    <p>{t('transfer.whatsapp_howto')}</p>
    {@render autoCheck(t('transfer.auto_check_wa'))}
  </div>
{/snippet}

{#snippet othersFold()}
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

{#snippet appsFold()}
  <ul class="flex flex-col gap-1 text-sm">
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
{/snippet}
