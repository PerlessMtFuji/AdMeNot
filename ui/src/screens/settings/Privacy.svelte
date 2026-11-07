<script lang="ts">
  import { getContext } from 'svelte';
  import PrivacyChoices from '../../components/PrivacyChoices.svelte';
  import RiskWarning from '../../components/RiskWarning.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Dialog from '../../ui/Dialog.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  const KEEP_DAYS = [30, 60, 90, 180, 365];
  const days = $derived(s.settings.retention_days === null ? KEEP_DAYS
    : [...new Set([...KEEP_DAYS, s.settings.retention_days])].sort((a, b) => a - b));

  let warning = $state(false);
  let idCopied = $state(false);

  async function saveRetention(select: HTMLSelectElement): Promise<void> {
    const r = await ctl.saveSettings({ retention_days: select.value ? Number(select.value) : null });
    if (!r) select.value = String(s.settings.retention_days ?? '');
  }

  // Odmowa schowka nie może trafić do `unhandledrejection` (main.ts przełączyłby UI w „fatal”).
  function copyId(): void {
    navigator.clipboard?.writeText(s.settings.telemetry_id ?? '').then(() => { idCopied = true; }).catch(() => {});
  }
</script>

<SettingGroup title={t('settings.group_customer_data')}>
  <SettingRow id="retention_days" label={t('settings.retention')} hint={t('settings.retention_hint')} keywords={t('settings.retention_title')}>
    <select aria-label={t('settings.retention')} class="field rounded-[10px] px-2.5 py-1.5 text-sm"
      value={String(s.settings.retention_days ?? '')} onchange={(e) => saveRetention(e.currentTarget)}>
      <option value="">{t('settings.retention_forever')}</option>
      {#each days as d (d)}<option value={String(d)}>{t('settings.retention_days', { days: d })}</option>{/each}
    </select>
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_stats')}>
  <PrivacyChoices rows telemetry={s.settings.telemetry} packages={s.settings.telemetry_packages}
    onchange={(tel, pkg) => ctl.setTelemetry(tel, pkg)} />
  {#if s.settings.telemetry_id}
    <SettingRow id="telemetry_id" label={t('privacy.id')} hint={t('privacy.id_hint')}>
      <code class="mono text-xs">{s.settings.telemetry_id}</code>
      <Button size="sm" variant="ghost" onclick={copyId}>{t('privacy.copy')}</Button>
      {#if idCopied}<span role="status" class="text-xs text-mut">{t('privacy.copied')}</span>{/if}
    </SettingRow>
  {/if}
  {#if s.settings.telemetry_delete_pending}
    <div class="border-t border-line px-4 py-2.5">
      <Banner tone="info" icon="info">{t('privacy.delete_pending')}</Banner>
    </div>
  {/if}
  <SettingRow id="show_warning" label={t('privacy.show_warning')} keywords={t('welcome.risk_title')}>
    <Button size="sm" onclick={() => (warning = true)}>{t('privacy.show_warning')}</Button>
  </SettingRow>
</SettingGroup>

{#if warning}
  <Dialog title={t('welcome.risk_title')} oncancel={() => (warning = false)}>
    <RiskWarning />
    {#snippet actions()}<Button onclick={() => (warning = false)}>{t('common.close')}</Button>{/snippet}
  </Dialog>
{/if}
