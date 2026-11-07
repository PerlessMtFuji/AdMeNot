<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import PathPicker from '../../components/settings/PathPicker.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import type { AdbSource } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import Toggle from '../../ui/Toggle.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  type AdbInfo = { ok: boolean; version: string | null; message: string; source: AdbSource };
  let adb = $state<AdbInfo | null>(null);
  let result = $state<AdbInfo | null>(null);

  // „Android Debug Bridge version 1.0.41” → „1.0.41”.
  const shortVersion = (v: string | null) => v?.match(/\d+(?:\.\d+)+/)?.[0] ?? v ?? '';
  const pill = $derived(adb
    ? [t(`settings.adb_source.${adb.source}`), adb.ok ? shortVersion(adb.version) : ''].filter(Boolean).join(' · ')
    : null);

  async function refreshAdb(): Promise<AdbInfo | null> {
    const r = await ctl.checkAdb(s.settings.adb_path);
    if (r) adb = r;
    return r;
  }

  onMount(() => { void refreshAdb(); });

  async function check(): Promise<void> {
    result = await refreshAdb();
  }

  const pickAdb = async () => (await ctl.pickAdb())?.path ?? null;

  async function saveAdb(path: string | null): Promise<void> {
    result = null;
    if (await ctl.saveSettings({ adb_path: path })) await refreshAdb();
  }

  const upToDate = $derived(s.update !== null && s.update.available === null);
</script>

<SettingGroup title={t('settings.updates_title')}>
  <SettingRow id="version" label={s.settings.last_run_version ? t('settings.version', { version: s.settings.last_run_version }) : 'AdMeNot'}
    hint={s.update?.available ? t('update.available', { version: s.update.available.version }) : upToDate ? t('settings.up_to_date') : undefined}
    keywords={`${t('settings.updates_title')} ${t('update.notes')}`}>
    {#if s.update?.available}
      <Button size="sm" onclick={() => ctl.openUpdate()}>{t('update.notes')}</Button>
    {/if}
  </SettingRow>
  <SettingRow id="check_updates" label={t('settings.check_updates')} hint={t('settings.check_updates_hint')}>
    <Toggle checked={s.settings.check_updates} label={t('settings.check_updates')}
      onchange={async (v) => (await ctl.saveSettings({ check_updates: v })) !== null} />
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_support')}>
  <SettingRow id="donate_reminders" label={t('donate.reminders')} hint={t('donate.reminders_hint')} keywords={t('donate.title')}>
    <Toggle checked={s.settings.donate_reminders} label={t('donate.reminders')}
      onchange={async (v) => { await ctl.setDonateReminders(v); return s.settings.donate_reminders === v; }} />
    <Button size="sm" onclick={() => ctl.openDonate()}><Icon name="heart" />{t('donate.support')}</Button>
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_advanced')}>
  <SettingRow id="adb_path" label={t('settings.adb')} hint={s.settings.adb_path ?? t('settings.adb_hint')} keywords="adb platform-tools">
    <PathPicker value={pill} placeholder={t('settings.adb_source.missing')} pick={pickAdb} onchange={saveAdb}
      clearable={s.settings.adb_path !== null} />
    <Button size="sm" onclick={check}>{t('settings.check')}</Button>
  </SettingRow>
  {#if result}
    <div class="border-t border-line px-4 py-2.5">
      {#if result.ok}
        <Banner tone="ok" icon="check">{t('settings.adb_ok', { version: result.version ?? '' })} · {t(`settings.adb_source.${result.source}`)}</Banner>
      {:else}
        <Banner tone="bad" icon="x">{t('settings.adb_fail', { message: result.message })}</Banner>
      {/if}
    </div>
  {/if}
</SettingGroup>
