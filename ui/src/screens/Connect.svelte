<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import ConnectChecklist from '../components/ConnectChecklist.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import DeviceList from '../components/DeviceList.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import MirrorControls from '../components/MirrorControls.svelte';
  import PhoneCleanup from '../components/PhoneCleanup.svelte';
  import PhoneStage from '../components/PhoneStage.svelte';
  import UsbGuide from '../components/UsbGuide.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { connectChecklist, linkState, modelName, restoreOffer, restoreResumable, resumableCopy } from '../lib/logic';
  import type { CopyView } from '../lib/types';
  import { enter } from '../lib/motion';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const link = $derived(linkState(s.devices, s.devicesError));
  const ready = $derived(s.devices.filter((d) => d.state === 'device'));
  const pending = $derived(s.devices.find((d) => d.state !== 'device') ?? null);
  const stage = $derived(link === 'ready' || link === 'many' ? 'ok'
    : link === 'unauthorized' ? 'auth' : link === 'offline' ? 'offline' : 'wait');
  const checks = $derived(connectChecklist(link));
  const known = $derived(pending !== null && s.knownSerials.includes(pending.serial));
  // Przerwana kopia danych (np. zamknięty program): propozycja wznowienia od razu po podłączeniu tego telefonu.
  const resumable = $derived(link === 'ready' || link === 'many' ? resumableCopy(s.transfer.copies, s.serial) : null);
  // Wgrywanie kopii na ten telefon: najpierw przerwane wgrywanie, potem propozycja świeżej kopii innego telefonu.
  const restoring = $derived(link === 'ready' || link === 'many' ? restoreResumable(s.transfer.copies, s.serial) : null);
  const offer = $derived(link === 'ready' || link === 'many' ? restoreOffer(s.transfer.copies, s.serial, new Date()) : null);
  // Ręczne wgrywanie: dowolna skończona kopia, także stara albo już wgrana (baner proponuje tylko świeżą).
  // Telefon wraca do ustawień sprzed przerwanego wgrywania: do końca most odmówi każdego zadania (`busy`).
  const cleaning = $derived(s.transfer.cleanup.running);
  const anyCopy = $derived(s.transfer.copies.some((c) => c.status === 'complete' || c.status === 'incomplete'));
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const source = (c: CopyView) => ({ phone: `${c.manufacturer} ${c.model}`.trim(),
    details: [c.client, when(c.created)].filter(Boolean).join(', ') });

  // „Pliki”: eksplorator trzyma telefon na wyłączność, więc nie przy trwającym zadaniu ani sprzątaniu.
  const ex = ctl.explorer.state;
  const filesReason = $derived(!s.serial ? t('explorer.files_reason.pick') : s.job ? t('explorer.files_reason.busy')
    : cleaning ? t('explorer.files_reason.cleanup') : null);

  /** „Inna kopia” i „Wgraj kopię”: lista kopii (z „Wgraj na podłączony telefon”) to zakładka Historii. */
  async function otherCopy(): Promise<void> {
    await ctl.openHistory(null, 'copies');
  }

  // Za każdym powrotem na ten ekran: kopia mogła się w międzyczasie skończyć albo przerwać.
  onMount(() => { void ctl.loadTransfers(); });
</script>

<main class="flex min-w-0 flex-1 gap-7 scroll-fade overflow-auto px-7 py-7">
  <div class="flex w-[260px] flex-none flex-col gap-3">
    <div>
      <h1 class="text-2xl font-extrabold">{t(`connect.title.${link}`)}</h1>
      <p class="mt-1 min-h-[44px] text-mut">{t(`connect.sub.${link}`)}</p>
    </div>
    <PhoneStage state={stage} />
    <ConnectChecklist label={t('connect.check.label')} items={[
      { label: t('connect.check.cable'), status: checks[0] },
      { label: t('connect.check.auth'), status: checks[1] },
      { label: t('connect.check.model'), status: checks[2] },
    ]} />
  </div>

  <div class="flex min-w-0 flex-1 flex-col gap-4">
    <PhoneCleanup />
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if ex.notice}
      <Banner tone={ex.notice === 'busy' ? 'warn' : 'info'} icon={ex.notice === 'busy' ? 'clock' : 'info'}
        title={ex.notice === 'busy' ? t('explorer.notice.busy_title') : undefined}>
        {t(`explorer.notice.${ex.notice}`)}
        {#snippet actions()}
          <Button size="sm" variant="ghost" onclick={() => ctl.explorer.dismissNotice()}>{t('common.close')}</Button>
        {/snippet}
      </Banner>
    {/if}
    {#if resumable}
      <Banner tone="info" icon="rotate-ccw" title={t('transfer.resume_title', { when: when(resumable.created) })}>
        {t('transfer.resume_text')}
        {#snippet actions()}
          <Button variant="primary" size="sm" disabled={cleaning} onclick={() => ctl.startTransfer(true)}>{t('transfer.resume')}</Button>
        {/snippet}
      </Banner>
    {:else if restoring}
      <Banner tone="info" icon="rotate-ccw" title={t('transfer.restore.resume_title')}>
        {t('transfer.restore.resume_text', source(restoring))}
        {#snippet actions()}
          <Button variant="primary" size="sm" disabled={cleaning} onclick={() => ctl.planRestore(restoring.id)}>{t('transfer.restore.resume')}</Button>
        {/snippet}
      </Banner>
    {:else if offer}
      <Banner tone="info" icon="smartphone" title={t('transfer.restore.offer_title', source(offer))}>
        {t('transfer.restore.offer_text')}
        {#snippet actions()}
          <Button variant="primary" size="sm" disabled={cleaning} onclick={() => ctl.planRestore(offer.id)}>{t('transfer.restore.upload')}</Button>
          <Button size="sm" onclick={otherCopy}>{t('transfer.restore.other_copy')}</Button>
        {/snippet}
      </Banner>
    {/if}
    {#if link === 'adb_missing'}
      <Banner tone="bad" icon="triangle-alert" title={t('connect.adb_missing')}>
        {#snippet actions()}<Button onclick={() => ctl.openSettings('program')}>{t('connect.open_settings')}</Button>{/snippet}
      </Banner>
    {:else if link === 'ready' || link === 'many'}
      <div class="flex flex-col gap-2.5" in:enter>
        {#if ready.length > 1}
          <DeviceList devices={ready} />
        {:else}
          {#each ready as d (d.serial)}
            <label class="block cursor-pointer rounded-2xl">
              <DeviceCard name={d.name ?? modelName(d.model)} details={t('connect.title.ready')} serial={d.serial} imei={d.imei} image={d.image} connected copyImei>
                <MirrorControls serial={d.serial} name={d.name ?? modelName(d.model)} />
              </DeviceCard>
            </label>
          {/each}
        {/if}
        <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); if (!cleaning) void ctl.startScan(); }}>
          <input class="field flex-1 rounded-xl px-3.5 py-2.5" bind:value={s.client}
            placeholder={t('connect.client_placeholder')} aria-label={t('connect.client_label')} maxlength="80" />
          <Button type="submit" variant="primary" size="lg" disabled={!s.serial || cleaning} title={filesReason ?? undefined}>{t('connect.scan')}</Button>
          <Button variant="secondary" size="lg" disabled={!s.serial || cleaning} title={filesReason ?? undefined} onclick={() => ctl.startTransfer()}>{t('transfer.start')}</Button>
          <Button variant="secondary" size="lg" disabled={filesReason !== null} title={filesReason ?? undefined}
            onclick={() => { if (s.serial) void ctl.explorer.open(s.serial); }}>
            <Icon name="folder-open" size={18} />{t('explorer.files')}
          </Button>
          {#if anyCopy}
            <Button variant="secondary" size="lg" disabled={!s.serial || cleaning} onclick={otherCopy}>{t('transfer.restore.pick')}</Button>
          {/if}
        </form>
      </div>
    {:else}
      <!-- nowy telefon albo historia wczytana po pierwszym renderze: przewodnik liczy stan od nowa -->
      {#key `${pending?.serial ?? ''}|${known}`}
        <UsbGuide model={pending?.model ?? null} collapsed={known} />
      {/key}
    {/if}
  </div>
</main>
