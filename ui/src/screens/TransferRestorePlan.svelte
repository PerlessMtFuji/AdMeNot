<script lang="ts">
  import Download from '@lucide/svelte/icons/download';
  import Film from '@lucide/svelte/icons/film';
  import Folder from '@lucide/svelte/icons/folder';
  import ImageIcon from '@lucide/svelte/icons/image';
  import MessageCircle from '@lucide/svelte/icons/message-circle';
  import MessageSquare from '@lucide/svelte/icons/message-square';
  import Phone from '@lucide/svelte/icons/phone';
  import Users from '@lucide/svelte/icons/users';
  import { getContext, type Snippet } from 'svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize, modelName, otherGroup, TEL_KINDS, telWrite, UPLOAD_GROUPS, uploadNeed } from '../lib/logic';
  import type { CopyView, RestoreApk, TelKind, UploadGroup, UploadTotals } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Row = { key: string; icon: typeof Folder; title: string; totals: UploadTotals; note?: string; checked: boolean };

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const r = $derived(s.transfer.restore);
  const plan = $derived(r.plan);
  const copy = $derived(r.copy);
  const choice = $derived(r.choice);
  const need = $derived(plan ? uploadNeed(plan, choice) : null);
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? entry?.name ?? modelName(entry?.model ?? null));
  const crumb = $derived([s.client.trim(), name, t('transfer.mode')].filter(Boolean).join(' · '));
  const serial = $derived(s.device?.serial ?? s.serial ?? '');
  const blocked = $derived(!need || !need.fits || (choice.groups.length === 0 && choice.tel.length === 0) || s.job !== null);
  // Ten sam telefon co w kopii (kopia < 24 h): pytanie z domyślnym „Nie”; „Tak” zostawia ekran wyboru.
  let sameConfirmed = $state(false);

  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const size = (bytes: number) => formatSize(bytes, i18n.lang);
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const source = (c: CopyView) => ({ phone: `${c.manufacturer} ${c.model}`.trim(),
    details: [c.client, when(c.created)].filter(Boolean).join(', ') });

  const ICONS: Record<UploadGroup, typeof Folder> = { photos: ImageIcon, videos: Film, downloads: Download, whatsapp: MessageCircle };
  const groupRows = $derived.by((): Row[] => {
    if (!plan) return [];
    return UPLOAD_GROUPS.flatMap((g) => {
      const totals = plan.groups[g];
      return totals ? [{ key: g, icon: ICONS[g], title: t(`transfer.restore.group.${g}`), totals,
        note: t(`transfer.restore.note.${g}`), checked: choice.groups.includes(g) }] : [];
    });
  });
  const othersRow = $derived.by((): Row | null => {
    if (!plan || !plan.others.length) return null;
    const sum = (k: keyof UploadTotals) => plan.others.reduce((n, o) => n + o[k], 0);
    return { key: 'others', icon: Folder, title: t('transfer.restore.group.others'),
      totals: { files: sum('files'), bytes: sum('bytes'), exists: sum('exists'), rename: sum('rename') },
      checked: plan.others.some((o) => choice.groups.includes(otherGroup(o.name))) };
  });

  // Kontakty, SMS (z MMS) i połączenia z kopii; kategorii, której w kopii nie ma, nie pokazujemy.
  const TEL_ICONS: Record<TelKind, typeof Folder> = { contacts: Users, sms: MessageSquare, calls: Phone };
  const telRows = $derived.by(() => {
    const tel = r.tel;
    if (!tel) return [];
    return TEL_KINDS.flatMap((kind) => {
      const write = telWrite(tel, kind);
      if (write === null) return [];
      // telefon, który nie dał się odczytać, nie mówi, ile już na nim jest (duplikatom zapobiega stan wgrywania)
      const existing = tel.readable[kind] === false ? 0
        : kind === 'sms' ? (tel.sms?.existing ?? 0) + (tel.mms?.existing ?? 0) : tel[kind]?.existing ?? 0;
      return [{ kind, icon: TEL_ICONS[kind], write, existing, checked: choice.tel.includes(kind) }];
    });
  });

  const incompleteParts = $derived.by(() => {
    const c = copy?.counts ?? {};
    return ([['files_failed', 'incomplete_files'], ['apps_failed', 'incomplete_apps'], ['unreadable', 'incomplete_unreadable']] as const)
      .filter(([k]) => (c[k] ?? 0) > 0).map(([k, label]) => t(`transfer.restore.${label}`, { count: num(c[k]) }));
  });

  function apkLabel(a: RestoreApk): { text: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' } {
    if (a.outcome === 'malicious') return { text: t('transfer.restore.apk.malicious'), tone: 'bad' };
    if (a.outcome === 'suspicious') {
      const on = a.default_on || choice.apks_on.includes(a.remote);
      return { text: t(`transfer.restore.apk.${on ? 'suspicious_on' : 'suspicious_off'}`), tone: 'warn' };
    }
    if (a.outcome === 'unknown') return { text: t('transfer.restore.apk.unknown'), tone: 'neutral' };
    return { text: t('transfer.restore.apk.clean'), tone: 'ok' };
  }

  // Pasek miejsca: zajęte przed wgraniem i to, co dojdzie (przy braku miejsca ucięte do wolnego).
  const bar = $derived.by(() => {
    if (!plan || !need) return null;
    const total = plan.space.total ?? plan.space.free + need.need;
    if (total <= 0) return null;
    const used = Math.max(0, total - plan.space.free);
    return { used: (used / total) * 100, add: (Math.min(need.need, plan.space.free) / total) * 100 };
  });
</script>

{#snippet row(row: Row, extra?: Snippet)}
  <div class="rounded-2xl card px-4 py-3 transition-opacity duration-150 {row.checked ? '' : 'opacity-70'}">
    <div class="flex items-start gap-3.5">
      <label class="flex min-w-0 flex-1 items-start gap-3.5 {row.totals.files ? 'cursor-pointer' : ''}">
        <input type="checkbox" class="mt-2.5 h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={row.checked}
          disabled={row.totals.files === 0} onchange={() => ctl.toggleUploadGroup(row.key)} />
        <span class="grid h-9 w-9 flex-none place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true"><row.icon size={18} /></span>
        <span class="min-w-0 flex-1">
          <span class="block font-bold">{row.title}
            <span class="ml-1 text-sm font-semibold text-soft">{tp('transfer.files', row.totals.files, { count: num(row.totals.files) })}</span></span>
          {#if row.note}<span class="block text-sm text-mut">{row.note}</span>{/if}
          {#if row.totals.exists || row.totals.rename}
            <span class="block text-sm text-mut">{[
              row.totals.exists ? t('transfer.restore.exists', { count: num(row.totals.exists) }) : '',
              row.totals.rename ? t('transfer.restore.rename', { count: num(row.totals.rename) }) : '',
            ].filter(Boolean).join(' · ')}</span>
          {/if}
        </span>
      </label>
      <span class="mono flex-none pt-1.5 text-sm text-mut">{size(row.totals.bytes)}</span>
    </div>
    {#if extra}<div class="mt-2 pl-[76px]">{@render extra()}</div>{/if}
  </div>
{/snippet}

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

      <span class="lbl mt-1">{t('transfer.restore.section_files')}</span>
      {#each groupRows as g (g.key)}{@render row(g)}{/each}
      {#if othersRow}{@render row(othersRow, others)}{/if}

      {#if plan.apks.length}
        <span class="lbl mt-2">{t('transfer.restore.section_apks')}</span>
        <div class="rounded-2xl card px-4 py-3">
          <p class="text-sm text-mut">{t('transfer.restore.apks_note')}</p>
          <ul class="mt-2 flex flex-col gap-1.5 text-sm">
            {#each plan.apks as a (a.remote)}
              {@const label = apkLabel(a)}
              {@const groupOn = choice.groups.includes(a.group)}
              <li class="flex items-center gap-2">
                {#if a.outcome === 'malicious'}
                  <span class="h-4 w-4 flex-none text-bad" aria-hidden="true"><Icon name="shield-x" size={16} /></span>
                  <span class="truncate">{a.name}</span>
                {:else}
                  <label class="flex min-w-0 items-center gap-2 {a.default_on ? '' : 'cursor-pointer'}">
                    <input type="checkbox" class="h-4 w-4 flex-none accent-[var(--color-accent)]"
                      checked={groupOn && (a.default_on || choice.apks_on.includes(a.remote))}
                      disabled={a.default_on || !groupOn} onchange={() => ctl.toggleUploadApk(a.remote)} />
                    <span class="truncate">{a.name}</span>
                  </label>
                {/if}
                <span class="text-soft">· {size(a.bytes)}</span>
                <Pill tone={label.tone}>{label.text}</Pill>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if telRows.length}
        <section aria-label={t('transfer.restore.section_tel')} class="mt-2 flex flex-col gap-3">
          <span class="lbl">{t('transfer.restore.section_tel')}</span>
          {#if r.tel?.phone_has_contacts}
            <Banner tone="info" icon="info" title={t('transfer.restore.tel.duplicates')} />
          {/if}
          {#each telRows as row (row.kind)}
            <div class="rounded-2xl card px-4 py-3 transition-opacity duration-150 {row.checked ? '' : 'opacity-70'}">
              <label class="flex min-w-0 items-start gap-3.5 {row.write ? 'cursor-pointer' : ''}">
                <input type="checkbox" class="mt-2.5 h-[18px] w-[18px] flex-none accent-[var(--color-accent)]" checked={row.checked}
                  disabled={row.write === 0} onchange={() => ctl.toggleTel(row.kind)} />
                <span class="grid h-9 w-9 flex-none place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true"><row.icon size={18} /></span>
                <span class="min-w-0 flex-1">
                  <span class="block font-bold">{t(`transfer.restore.tel.${row.kind}`)}</span>
                  <span class="block text-sm text-mut">{[
                    t('transfer.restore.tel.to_write', { count: num(row.write) }),
                    row.existing ? t('transfer.restore.exists', { count: num(row.existing) }) : '',
                  ].filter(Boolean).join(' · ')}</span>
                  {#if row.kind === 'contacts' && r.tel?.contacts}
                    {#each r.tel.contacts.skipped_synced as a (a.account)}
                      <span class="block text-sm text-mut">{tp('transfer.restore.tel.synced', a.count, { count: num(a.count), account: a.account })}</span>
                    {/each}
                    {#if r.tel.contacts.skipped_messenger}
                      <span class="block text-sm text-mut">{tp('transfer.restore.tel.messenger', r.tel.contacts.skipped_messenger,
                        { count: num(r.tel.contacts.skipped_messenger) })}</span>
                    {/if}
                  {/if}
                </span>
              </label>
            </div>
          {/each}
        </section>
      {/if}

      <section aria-label={t('transfer.restore.later_title')} class="mt-2 flex flex-col gap-1.5">
        <span class="lbl">{t('transfer.restore.later_title')}</span>
        <ul class="flex flex-col gap-1 rounded-2xl border border-dashed border-line px-4 py-3 text-sm text-soft">
          {#each ['apps', 'whatsapp'] as k (k)}
            <li class="flex items-center justify-between gap-3">
              <span>{t(`transfer.restore.later.${k}`)}</span><span class="text-xs">{t('transfer.restore.next_version')}</span>
            </li>
          {/each}
        </ul>
      </section>
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
      <Button variant="primary" size="lg" class="flex-col !gap-0" disabled={blocked} onclick={() => ctl.startRestore()}>
        {t('transfer.restore.begin')}
        <small class="text-xs font-semibold opacity-85">{size(need.need)}</small>
      </Button>
    {/if}
  </SidePanel>
</div>

{#snippet others()}
  <div class="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
    {#each plan?.others ?? [] as o (o.name)}
      <label class="flex cursor-pointer items-center gap-2">
        <input type="checkbox" class="h-4 w-4 accent-[var(--color-accent)]" checked={choice.groups.includes(otherGroup(o.name))}
          disabled={o.files === 0} onchange={() => ctl.toggleUploadGroup(otherGroup(o.name))} />
        <span>{o.name || t('transfer.row.root')} <span class="text-soft">· {size(o.bytes)}</span></span>
      </label>
    {/each}
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
