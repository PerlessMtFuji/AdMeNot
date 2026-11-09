<script lang="ts">
  import Download from '@lucide/svelte/icons/download';
  import Film from '@lucide/svelte/icons/film';
  import Folder from '@lucide/svelte/icons/folder';
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
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize, installableApps, modelName, otherGroup, restoreEtaMin, TEL_KINDS, telWrite, UPLOAD_GROUPS, uploadNeed } from '../lib/logic';
  import { recheck } from '../lib/recheck';
  import type { CopyView, RestoreApk, TelKind, UploadGroup } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Glyph = Component<{ size?: number; strokeWidth?: number; 'aria-hidden'?: 'true' }>;

  /** Ile pominiętych aplikacji wymieniamy w szarej linii; reszta to „… i N innych”. */
  const SKIP_LISTED = 6;

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const r = $derived(s.transfer.restore);
  const plan = $derived(r.plan);
  const copy = $derived(r.copy);
  const choice = $derived(r.choice);
  const apps = $derived(r.apps);
  const need = $derived(plan ? uploadNeed(plan, choice, apps) : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const serial = $derived(s.device?.serial ?? s.serial ?? '');
  const nothing = $derived(choice.groups.length === 0 && choice.tel.length === 0 && choice.apps.length === 0);
  // Blokada Xiaomi nie wyłącza „Wgraj”: reszta idzie, a aplikacje silnik pomija jako zablokowane.
  const blocked = $derived(!need || !need.fits || nothing || s.job !== null);
  // Ten sam telefon co w kopii (kopia < 24 h): pytanie z domyślnym „Nie”; „Tak” zostawia ekran wyboru.
  let sameConfirmed = $state(false);

  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const source = (c: CopyView) => ({ phone: `${c.manufacturer} ${c.model}`.trim(),
    details: [c.client, when(c.created)].filter(Boolean).join(', ') });

  // Rozwinięcia sterowane stąd tylko tam, gdzie od nich zależy treść (aplikacje: instrukcja Xiaomi otwiera listę).
  let appsOpen = $state(false);
  let howOpen = $state(false);
  function toggleHow() {
    howOpen = !howOpen;
    if (howOpen) appsOpen = true;
  }

  // --- Kontakty i wiadomości: kontakty, SMS (z MMS) i połączenia z kopii; kategorii, której w kopii nie ma, nie pokazujemy.
  const TEL_ICONS: Record<TelKind, Glyph> = { contacts: Users, sms: MessageSquare, calls: Phone };
  const telRows = $derived.by(() => {
    const tel = r.tel;
    if (!tel) return [];
    return TEL_KINDS.flatMap((kind) => {
      const write = telWrite(tel, kind);
      if (write === null) return [];
      // telefon, który nie dał się odczytać, nie mówi, ile już na nim jest (duplikatom zapobiega stan wgrywania)
      const existing = tel.readable[kind] === false ? 0
        : kind === 'sms' ? (tel.sms?.existing ?? 0) + (tel.mms?.existing ?? 0) : tel[kind]?.existing ?? 0;
      const notes = [existing ? t('transfer.restore.exists', { count: num(existing) }) : ''];
      if (kind === 'contacts' && tel.contacts) {
        if (tel.phone_has_contacts) notes.push(t('transfer.restore.tel.duplicates'));
        for (const a of tel.contacts.skipped_synced) {
          notes.push(tp('transfer.restore.tel.synced', a.count, { count: num(a.count), account: a.account }));
        }
        if (tel.contacts.skipped_messenger) {
          notes.push(tp('transfer.restore.tel.messenger', tel.contacts.skipped_messenger, { count: num(tel.contacts.skipped_messenger) }));
        }
      }
      return [{ kind, icon: TEL_ICONS[kind], name: t(`transfer.restore.tel.${kind}`), write,
        sub: notes.filter(Boolean).join(' · ') || undefined, checked: choice.tel.includes(kind) }];
    });
  });
  const telMissing = $derived(r.tel ? TEL_KINDS.filter((k) => telWrite(r.tel, k) === null).map((k) => t(`transfer.restore.tel.${k}`)).join(', ') : '');

  // --- Pliki
  const ICONS: Record<UploadGroup, Glyph> = { photos: ImageIcon, videos: Film, downloads: Download, whatsapp: MessageCircle };
  const fileRows = $derived.by(() => {
    if (!plan) return [];
    return UPLOAD_GROUPS.flatMap((g) => {
      const totals = plan.groups[g];
      if (!totals || totals.files === 0) return [];
      const notes = [g === 'whatsapp' ? t('transfer.restore.note.whatsapp') : '',
        totals.exists ? t('transfer.restore.exists', { count: num(totals.exists) }) : '',
        totals.rename ? t('transfer.restore.rename', { count: num(totals.rename) }) : ''];
      return [{ key: g, icon: ICONS[g], name: t(`transfer.restore.group.${g}`), totals, sub: notes.filter(Boolean).join(' · ') || undefined,
        checked: choice.groups.includes(g) }];
    });
  });
  const folders = $derived(plan?.others.filter((o) => o.files > 0) ?? []);
  const othersBytes = $derived(folders.reduce((n, o) => n + o.bytes, 0));
  const filesMissing = $derived.by(() => {
    if (!plan) return '';
    const present = new Set(fileRows.map((row) => row.key));
    return [...UPLOAD_GROUPS.filter((g) => !present.has(g)).map((g) => t(`transfer.restore.group.${g}`)),
      ...(folders.length ? [] : [t('transfer.restore.group.others')])].join(', ');
  });

  // Pigułki wiersza „Pobrane”: szkodliwe APK pomijamy, podejrzane są odznaczone, dopóki serwisant ich nie zaznaczy.
  const apkOn = (a: RestoreApk) => choice.groups.includes(a.group) && (a.default_on || choice.apks_on.includes(a.remote));
  const apkHarmful = $derived(plan?.apks.filter((a) => a.outcome === 'malicious').length ?? 0);
  const apkUnticked = $derived(plan?.apks.filter((a) => a.outcome === 'suspicious' && !apkOn(a)).length ?? 0);

  function apkLabel(a: RestoreApk): { text: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' } {
    if (a.outcome === 'malicious') return { text: t('transfer.restore.apk.malicious'), tone: 'bad' };
    if (a.outcome === 'suspicious') {
      const on = a.default_on || choice.apks_on.includes(a.remote);
      return { text: t(`transfer.restore.apk.${on ? 'suspicious_on' : 'suspicious_off'}`), tone: 'warn' };
    }
    if (a.outcome === 'unknown') return { text: t('transfer.restore.apk.unknown'), tone: 'neutral' };
    return { text: t('transfer.restore.apk.clean'), tone: 'ok' };
  }

  // --- Aplikacje: lista do wyboru bez pominiętych; pominięte to jedna szara linia na dole rozwinięcia.
  const installable = $derived(installableApps(apps));
  const skipped = $derived((apps?.items ?? []).filter((a) => a.skip));
  const appsBytes = $derived(installable.filter((a) => choice.apps.includes(a.package)).reduce((n, a) => n + a.bytes, 0));
  const appsSuspicious = $derived(installable.filter((a) => a.verdict === 'suspicious' && !choice.apps.includes(a.package)).length);
  const android = $derived(s.device?.android ?? null);
  const reason = (skip: NonNullable<(typeof skipped)[number]['skip']>) => skip === 'too_old'
    ? (android ? t('transfer.restore.apps_reason.too_old', { version: android }) : t('transfer.restore.apps_reason.too_old_unknown'))
    : t(`transfer.restore.apps_reason.${skip}`);
  const skipLine = $derived.by(() => {
    const items = skipped.slice(0, SKIP_LISTED).map((a) => t('transfer.restore.apps_skip_item', { name: a.name, reason: reason(a.skip!) }));
    if (skipped.length > SKIP_LISTED) items.push(t('transfer.restore.apps_skip_more', { count: num(skipped.length - SKIP_LISTED) }));
    return t('transfer.restore.apps_skip', { list: items.join(' · ') });
  });

  // Czas: pliki jak przy kopii, każda aplikacja dochodzi z instalacją.
  const etaMin = $derived(need ? restoreEtaMin(need.need, choice.apps.length) : 0);

  // Pasek miejsca: zajęte przed wgraniem i to, co dojdzie (przy braku miejsca ucięte do wolnego).
  const bar = $derived.by(() => {
    if (!plan || !need) return null;
    const total = plan.space.total ?? plan.space.free + need.need;
    if (total <= 0) return null;
    const used = Math.max(0, total - plan.space.free);
    return { used: (used / total) * 100, add: (Math.min(need.need, plan.space.free) / total) * 100 };
  });

  const incompleteParts = $derived.by(() => {
    const c = copy?.counts ?? {};
    return ([['files_failed', 'incomplete_files'], ['apps_failed', 'incomplete_apps'], ['unreadable', 'incomplete_unreadable']] as const)
      .filter(([k]) => (c[k] ?? 0) > 0).map(([k, label]) => t(`transfer.restore.${label}`, { count: num(c[k]) }));
  });

  // Zamiast „Sprawdź ponownie”: póki blokada Xiaomi trwa, program sam co RECHECK_MS pyta telefon (tani odczyt bez zadania).
  // Trwające zadanie na telefonie i pytanie o ten sam telefon wstrzymują sprawdzanie.
  $effect(() => {
    const stop = recheck(() => ctl.checkInstall(), () => !!r.apps?.block && s.job === null && !(r.sameRecent && !sameConfirmed));
    return stop;
  });
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-3 scroll-fade overflow-auto px-7 py-7">
    <div class="flex items-start gap-3">
      <div class="min-w-0 flex-1">
        <div class="text-sm font-semibold text-soft">{crumb}</div>
        <h1 class="text-2xl font-extrabold">{plan ? t('transfer.restore.title') : t('transfer.restore.planning')}</h1>
        <p class="text-mut">{plan && copy ? t('transfer.restore.sub', source(copy)) : t('transfer.restore.planning_sub')}</p>
      </div>
      <Button variant="ghost" size="sm" onclick={() => ctl.leaveTransfer()}><Icon name="arrow-left" size={14} />{t('common.back')}</Button>
    </div>

    {#if !plan}
      <div class="flex items-center gap-2 font-semibold text-mut"><Spinner />{t('transfer.restore.planning')}</div>
    {:else}
      {#if r.resumable}<Banner tone="info" icon="rotate-ccw" title={t('transfer.restore.resumable')} />{/if}
      {#if copy?.status === 'incomplete'}
        <Banner tone="warn" icon="triangle-alert" title={t('transfer.restore.incomplete_title')}>
          {incompleteParts.length ? t('transfer.restore.incomplete_text', { list: incompleteParts.join(', ') }) : t('transfer.restore.incomplete_unknown')}
        </Banner>
      {/if}
      {#if plan.missing > 0}
        <Banner tone="warn" icon="triangle-alert" title={tp('transfer.restore.missing', plan.missing, { count: num(plan.missing) })}>
          {t('transfer.restore.missing_text')}
        </Banner>
      {/if}

      {#if telRows.length}
        <CategoryGroup title={t('transfer.group.messages')} empty={telMissing}>
          {#each telRows as row (row.kind)}
            <CategoryRow icon={row.icon} name={row.name} count={num(row.write)} sub={row.sub} checked={row.checked}
              disabled={row.write === 0} ontoggle={() => ctl.toggleTel(row.kind)} />
          {/each}
        </CategoryGroup>
      {/if}

      <CategoryGroup title={t('transfer.group.files')} empty={filesMissing}>
        {#each fileRows as row (row.key)}
          {#if row.key === 'downloads' && plan.apks.length}
            <CategoryRow icon={row.icon} name={row.name} count={num(row.totals.files)} size={size(row.totals.bytes)} sub={row.sub}
              checked={row.checked} ontoggle={() => ctl.toggleUploadGroup(row.key)} fold={apkFold} foldLabel={row.name}>
              {#snippet pills()}
                {#if apkHarmful}<Pill tone="bad">{tp('transfer.restore.apk_malicious', apkHarmful, { count: num(apkHarmful) })}</Pill>{/if}
                {#if apkUnticked}<Pill tone="warn">{tp('transfer.restore.apk_suspicious', apkUnticked, { count: num(apkUnticked) })}</Pill>{/if}
              {/snippet}
            </CategoryRow>
          {:else}
            <CategoryRow icon={row.icon} name={row.name} count={num(row.totals.files)} size={size(row.totals.bytes)} sub={row.sub}
              checked={row.checked} ontoggle={() => ctl.toggleUploadGroup(row.key)} />
          {/if}
        {/each}
        {#if folders.length}
          <CategoryRow icon={Folder} name={t('transfer.restore.group.others')} count={num(folders.length)} size={size(othersBytes)}
            checked={folders.some((o) => choice.groups.includes(otherGroup(o.name)))} ontoggle={() => ctl.toggleUploadGroup('others')}
            fold={othersFold} foldLabel={t('transfer.restore.group.others')} />
        {/if}
      </CategoryGroup>

      {#if apps}
        <CategoryGroup title={t('transfer.group.apps')} empty={apps.items.length === 0 ? t('transfer.row.apps') : undefined}>
          {#if apps.items.length}
            <CategoryRow icon={LayoutGrid} name={t('transfer.row.apps')} count={t('transfer.restore.apps_count', { n: num(choice.apps.length), m: num(apps.items.length) })}
              sub={t('transfer.restore.apps_note')} size={choice.apps.length ? size(appsBytes) : undefined} checked={choice.apps.length > 0}
              disabled={installable.length === 0} ontoggle={() => ctl.toggleRestoreApps()} tone={apps.block ? 'block' : null}
              fold={appsFold} foldLabel={t('transfer.row.apps')} foldOpen={appsOpen} onfold={(open) => (appsOpen = open)}>
              {#snippet pills()}
                {#if appsSuspicious}<Pill tone="warn">{tp('transfer.apps_suspicious', appsSuspicious, { count: num(appsSuspicious) })}</Pill>{/if}
                {#if apps.block}
                  <button type="button" aria-expanded={howOpen} aria-controls="xiaomi-how" onclick={toggleHow}
                    class="inline-flex cursor-pointer items-center rounded-full bg-warn-soft px-2.5 py-0.5 text-xs font-bold whitespace-nowrap text-warn ring-1 ring-current/15 ring-inset hover:underline">
                    {t('transfer.restore.xiaomi_label')}
                  </button>
                {/if}
              {/snippet}
            </CategoryRow>
          {/if}
        </CategoryGroup>
      {/if}
    {/if}
  </main>

  <SidePanel label={t('transfer.restore.panel')}>
    <DeviceCard compact name={name} {serial} imei={s.device?.imei ?? entry?.imei} image={s.device?.image ?? null}
      details={s.device ? `${s.device.model} · Android ${s.device.android}` : modelName(entry?.model ?? null)} connected />
    {#if plan && need}
      <span class="lbl mt-2">{t('transfer.restore.panel')}</span>
      {#if bar}
        <div role="img" aria-label={t('transfer.restore.space_label')}
          class="flex h-2 overflow-hidden rounded-full bg-neutral-soft shadow-[var(--shadow-well)]">
          <i class="block h-full bg-[var(--color-soft)] opacity-50" style="width: {bar.used}%"></i>
          <i class="block h-full {need.fits ? 'bg-accent' : 'bg-warn-strong'}" style="width: {bar.add}%"></i>
        </div>
      {/if}
      <dl class="flex flex-col gap-1.5 text-sm">
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.restore.to_upload')}</dt><dd class="font-bold">{size(need.need)}</dd></div>
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.restore.free')}</dt><dd class="font-bold">{size(plan.space.free)}</dd></div>
        <div class="flex justify-between gap-3"><dt class="text-mut">{t('transfer.restore.reserve')}</dt><dd class="font-bold">{size(plan.reserve)}</dd></div>
      </dl>
      {#if need.fits}
        <p class="text-sm font-semibold text-ok">{t('transfer.restore.left', { size: size(plan.space.free - need.need) })}</p>
      {:else}
        <Banner tone="warn" icon="triangle-alert" title={t('transfer.restore.no_space', { size: size(need.missing) })} />
      {/if}
      {#if r.choice.tel.length > 0}
        <!-- kopia bezpieczeństwa nowego telefonu powstaje tylko przed telefonią -->
        <div class="flex items-start gap-2.5 rounded-xl bg-neutral-soft p-3 text-sm text-mut">
          <span class="mt-0.5 flex-none text-soft"><Icon name="lock" size={15} /></span><span>{t('transfer.restore.safety')}</span>
        </div>
      {/if}
      <Button variant="primary" size="lg" class="flex-col !gap-0" disabled={blocked} onclick={() => ctl.startRestore()}>
        {t('transfer.restore.begin')}
        <small class="text-xs font-semibold opacity-85">{size(need.need)} · {t('transfer.eta_value', { min: etaMin })}</small>
      </Button>
    {/if}
  </SidePanel>
</div>

<!-- Pobrane i dokumenty: pliki APK z kopii, ocenione na komputerze. Szkodliwego nie da się zaznaczyć. -->
{#snippet apkFold()}
  <div class="flex flex-col gap-2">
    <p>{t('transfer.restore.apks_note')}</p>
    <ul class="flex flex-col gap-1.5">
      {#each plan?.apks ?? [] as a (a.remote)}
        {@const label = apkLabel(a)}
        {@const groupOn = choice.groups.includes(a.group)}
        <li class="flex items-center gap-2">
          {#if a.outcome === 'malicious'}
            <span class="h-4 w-4 flex-none text-bad" aria-hidden="true"><Icon name="shield-x" size={16} /></span>
            <span class="truncate text-ink">{a.name}</span>
          {:else}
            <label class="flex min-w-0 items-center gap-2 {a.default_on ? '' : 'cursor-pointer'}">
              <input type="checkbox" class="h-4 w-4 flex-none accent-[var(--color-accent)]"
                checked={groupOn && (a.default_on || choice.apks_on.includes(a.remote))}
                disabled={a.default_on || !groupOn} onchange={() => ctl.toggleUploadApk(a.remote)} />
              <span class="truncate text-ink">{a.name}</span>
            </label>
          {/if}
          <span class="text-soft">· {size(a.bytes)}</span>
          <Pill tone={label.tone}>{label.text}</Pill>
        </li>
      {/each}
    </ul>
  </div>
{/snippet}

{#snippet othersFold()}
  <div class="flex flex-wrap gap-x-5 gap-y-1.5">
    {#each folders as o (o.name)}
      <label class="flex cursor-pointer items-center gap-2">
        <input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={choice.groups.includes(otherGroup(o.name))}
          onchange={() => ctl.toggleUploadGroup(otherGroup(o.name))} />
        <span class="text-ink">{o.name || t('transfer.row.root')} <span class="text-soft">· {size(o.bytes)}</span></span>
      </label>
    {/each}
  </div>
{/snippet}

<!-- Aplikacje: instrukcja Xiaomi tylko po kliknięciu etykiety, potem lista do wyboru i jedna szara linia o pominiętych. -->
{#snippet appsFold()}
  <div class="flex flex-col gap-2.5">
    {#if apps?.block && howOpen}
      <p id="xiaomi-how" class="rounded-xl border border-warn/30 bg-warn-soft px-3 py-2 text-warn">{t('transfer.restore.xiaomi_how')}</p>
    {/if}
    <ul class="grid max-h-72 grid-cols-2 gap-x-6 gap-y-1.5 overflow-auto pr-1">
      {#each installable as a (a.package)}
        <li class="min-w-0">
          <label class="flex cursor-pointer items-center gap-2">
            <input type="checkbox" class="h-4 w-4 flex-none accent-[var(--color-accent)]" checked={choice.apps.includes(a.package)}
              onchange={() => ctl.toggleRestoreApp(a.package)} />
            <span class="min-w-0 flex-1 truncate text-ink" title={a.package}>{a.name}</span>
            {#if a.verdict === 'suspicious'}<Pill tone="warn">{t('transfer.suspicious')}</Pill>{/if}
            <span class="mono flex-none text-2xs text-soft">{size(a.bytes)}</span>
          </label>
        </li>
      {/each}
    </ul>
    {#if skipped.length}<p class="text-soft">{skipLine}</p>{/if}
  </div>
{/snippet}

{#if plan && r.sameRecent && !sameConfirmed}
  <Dialog title={t('transfer.restore.same_title')} oncancel={() => ctl.leaveTransfer()}>
    {t('transfer.restore.same_text')}
    {#snippet actions()}
      <Button onclick={() => ctl.leaveTransfer()}>{t('transfer.restore.same_no')}</Button>
      <Button variant="primary" onclick={() => (sameConfirmed = true)}>{t('transfer.restore.same_yes')}</Button>
    {/snippet}
  </Dialog>
{/if}
