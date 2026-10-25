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
  import { formatSize, isXiaomi, modelName, transferNeed, transferTotals, whatsappStale } from '../lib/logic';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  type Row = { key: string; icon: typeof Users; title: string; meta: string; note?: string; bytes: number | null;
    checked: boolean; disabled: boolean };

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

  const phoneRows = $derived.by((): Row[] => {
    if (!inv) return [];
    const messages = inv.sms === null && inv.mms === null ? null : (inv.sms ?? 0) + (inv.mms ?? 0);
    return [
      { key: 'contacts', icon: Users, title: t('transfer.row.contacts'), meta: inv.contacts === null ? t('transfer.unavailable') : num(inv.contacts),
        note: t('transfer.row.contacts_note'), bytes: null, checked: sel.contacts, disabled: !readable(inv.contacts) },
      { key: 'sms', icon: MessageSquare, title: t('transfer.row.sms'), meta: count(messages, 'transfer.messages'),
        note: t('transfer.row.sms_note'), bytes: readable(inv.mms) ? inv.mms_bytes : null, checked: sel.sms || sel.mms,
        disabled: !readable(inv.sms) && !readable(inv.mms) },
      { key: 'calls', icon: PhoneIcon, title: t('transfer.row.calls'), meta: inv.calls === null ? t('transfer.unavailable') : num(inv.calls),
        bytes: null, checked: sel.calls, disabled: !readable(inv.calls) },
    ];
  });
  const phoneUnreadable = $derived(!!inv && (inv.contacts === null || inv.sms === null || inv.mms === null || inv.calls === null));

  function fileRow(key: 'media' | 'downloads' | 'whatsapp', icon: typeof Users, note: string): Row {
    const c = inv!.categories[key];
    return { key, icon, title: t(`transfer.row.${key}`), meta: tp('transfer.files', c.files, { count: num(c.files) }), note,
      bytes: c.bytes, checked: sel.categories.includes(key), disabled: c.files === 0 };
  }
  const othersBytes = $derived(inv?.others.reduce((n, o) => n + o.bytes, 0) ?? 0);
  const suspicious = $derived(inv?.apps.filter((a) => a.verdict === 'suspicious').length ?? 0);
  const waOld = $derived(!!inv && inv.categories.whatsapp.files > 0 && whatsappStale(inv.whatsapp_backup, new Date()));
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
          {#if r.note}<span class="block text-sm text-mut">{r.note}</span>{/if}
        </span>
      </label>
      <span class="mono flex-none pt-1.5 text-sm text-mut">{r.bytes !== null ? size(r.bytes) : ''}</span>
    </div>
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
      {#if phoneUnreadable}
        {#if isXiaomi(s.device)}
          <Banner tone="warn" icon="triangle-alert" title={t('transfer.unreadable')}>{t('transfer.xiaomi_hint')}</Banner>
        {:else}
          <Banner tone="warn" icon="triangle-alert" title={t('transfer.unreadable')} />
        {/if}
      {/if}

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
        note: t('transfer.row.apps_note'), bytes: null, checked: sel.apps.length > 0, disabled: inv.apps.length === 0 }, apps)}
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
        <span class="mt-0.5 flex-none text-soft"><Icon name="lock" size={15} /></span><span>{t('transfer.privacy')}</span>
      </div>
      <Button variant="primary" size="lg" class="flex-col !gap-0" disabled={blocked} onclick={() => ctl.startBackup()}>
        {t('transfer.begin')}
        <small class="text-xs font-semibold opacity-85">{tp('transfer.categories', totals.categories)} · {size(totals.bytes)}</small>
      </Button>
    {/if}
  </SidePanel>
</div>

{#snippet whatsapp()}
  {@const backup = inv?.whatsapp_backup ?? null}
  <Banner tone="warn" icon="info" title={backup ? t('transfer.whatsapp_old_title') : t('transfer.whatsapp_none_title')}>
    {backup ? t('transfer.whatsapp_old', { when: when(backup) }) : t('transfer.whatsapp_none')}
    {#snippet actions()}
      <Button size="sm" onclick={() => ctl.recheckWhatsapp()}>{t('transfer.recheck')}</Button>
    {/snippet}
  </Banner>
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
          </label>
        </li>
      {/each}
    </ul>
  {/if}
{/snippet}
