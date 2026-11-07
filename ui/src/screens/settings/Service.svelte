<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import PathPicker from '../../components/settings/PathPicker.svelte';
  import ProtocolPreview from '../../components/settings/ProtocolPreview.svelte';
  import { useSettingsSearch } from '../../components/settings/search.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import type { ServiceInfo } from '../../lib/types';
  import Toggle from '../../ui/Toggle.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const search = useSettingsSearch();

  const FOOTER_MAX = 500;
  type TextKey = 'name' | 'address' | 'phone' | 'email' | 'nip' | 'website' | 'technician' | 'footer';
  const EMPTY: Record<TextKey, string> = { name: '', address: '', phone: '', email: '', nip: '', website: '', technician: '', footer: '' };

  // `saved` = ostatnia wartość znana mostowi; `draft` = to, co jest w polach (podgląd rośnie z `draft`, przed zapisem).
  let saved = $state<ServiceInfo | null>(null);
  let draft = $state<Record<TextKey, string>>({ ...EMPTY });
  let logoError = $state<string | null>(null);
  let pdfBad = $state(false);

  const logo = $derived(saved?.logo ?? null);
  const footerTooLong = $derived(draft.footer.length > FOOTER_MAX);

  function adopt(info: ServiceInfo): void {
    saved = info;
  }

  onMount(async () => {
    const info = await ctl.loadService();
    if (!info) return;
    adopt(info);
    // Pole, w którym użytkownik zdążył już coś wpisać, zostaje.
    for (const k of Object.keys(EMPTY) as TextKey[]) if (draft[k] === '') draft[k] = info[k] ?? '';
  });

  async function commit(key: TextKey): Promise<void> {
    const value = draft[key].trim();
    if ((saved?.[key] ?? '') === value) return;
    if (key === 'footer' && draft.footer.length > FOOTER_MAX) return;
    const r = await ctl.saveService({ [key]: value });
    if (r) adopt(r);
  }

  async function saveLogo(path: string | null): Promise<void> {
    logoError = null;
    const r = await ctl.saveService({ logo: path });
    if (r) { adopt(r); return; }
    if (s.error?.key.startsWith('logo_')) { logoError = t(`error.${s.error.key}`); s.error = null; }
  }

  async function savePdfDir(path: string | null): Promise<void> {
    pdfBad = false;
    const r = await ctl.saveSettings({ report_pdf_dir: path });
    pdfBad = r === null && s.error?.key === 'bad_request' && s.error.message === 'report_pdf_dir';
    if (pdfBad) s.error = null;
  }

  const pickLogo = async () => (await ctl.pickLogo())?.path ?? null;
  const pickDir = async () => (await ctl.pickFolder())?.path ?? null;

  const FIELDS: { key: TextKey; label: string; id: string; keywords?: string; type?: string }[] = [
    { key: 'name', label: 'settings.service_name', id: 'service_name' },
    { key: 'address', label: 'settings.service_address', id: 'service_address' },
    { key: 'phone', label: 'settings.service_phone', id: 'service_phone', type: 'tel' },
    { key: 'email', label: 'settings.service_email', id: 'service_email', keywords: 'mail', type: 'email' },
    { key: 'nip', label: 'settings.service_nip', id: 'service_nip' },
    { key: 'website', label: 'settings.service_website', id: 'service_website', keywords: 'www', type: 'url' },
  ];
</script>

<SettingGroup title={t('settings.service_title')}>
  {#each FIELDS as f (f.id)}
    <SettingRow id={f.id} label={t(f.label)} hint={f.key === 'name' ? t('settings.service_hint') : undefined} keywords={f.keywords}>
      <input type={f.type ?? 'text'} aria-label={t(f.label)} bind:value={draft[f.key]} onblur={() => commit(f.key)}
        class="field w-[300px] rounded-[10px] px-2.5 py-1.5 text-sm {f.key === 'name' && draft.name.trim() === '' ? 'border-warn-strong' : ''}" />
    </SettingRow>
  {/each}
  <SettingRow id="service_logo" label={t('settings.service_logo')} hint={t('settings.logo_hint')} error={logoError}>
    <PathPicker value={logo} placeholder={t('settings.logo_none')} pick={pickLogo} onchange={saveLogo} clearable />
  </SettingRow>
  <SettingRow id="service_technician" label={t('settings.service_technician')} hint={t('settings.service_technician_hint')}
    keywords="podpis">
    <input type="text" aria-label={t('settings.service_technician')} bind:value={draft.technician}
      onblur={() => commit('technician')} class="field w-[300px] rounded-[10px] px-2.5 py-1.5 text-sm" />
  </SettingRow>
  <SettingRow id="service_footer" label={t('settings.service_footer')} hint={t('settings.service_footer_hint')}
    keywords="gwarancja">
    <span class="flex w-[300px] flex-col items-end gap-1">
      <textarea rows="3" aria-label={t('settings.service_footer')} bind:value={draft.footer} onblur={() => commit('footer')}
        class="field w-full resize-y rounded-[10px] px-2.5 py-1.5 text-sm"></textarea>
      <span class="text-xs {footerTooLong ? 'font-bold text-bad' : 'text-soft'}">{draft.footer.length}/{FOOTER_MAX}</span>
    </span>
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_protocols')}>
  <SettingRow id="report_pdf_dir" label={t('settings.report_pdf')} hint={t('settings.report_pdf_hint')} keywords="pdf"
    error={pdfBad ? t('settings.report_pdf_bad') : null}>
    <PathPicker value={s.settings.report_pdf_dir} placeholder={t('settings.report_pdf_default')} pick={pickDir}
      onchange={savePdfDir} clearable />
  </SettingRow>
  <SettingRow id="report_open" label={t('settings.report_open')} hint={t('settings.report_open_hint')}>
    <Toggle checked={s.settings.report_open} label={t('settings.report_open')}
      onchange={async (v) => (await ctl.saveSettings({ report_open: v })) !== null} />
  </SettingRow>
</SettingGroup>

{#if search.query.trim() === ''}
  <ProtocolPreview info={{ ...draft, logo }} />
{/if}
