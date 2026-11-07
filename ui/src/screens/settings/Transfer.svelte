<script lang="ts">
  import { getContext } from 'svelte';
  import PathPicker from '../../components/settings/PathPicker.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import Toggle from '../../ui/Toggle.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  const KEEP_DAYS = [3, 7, 14, 30];
  const keep = $derived([...new Set([...KEEP_DAYS, s.settings.transfer_keep_days])].sort((a, b) => a - b));
  let dirBad = $state(false);

  const pickDir = async () => (await ctl.pickFolder())?.path ?? null;

  async function saveDir(path: string | null): Promise<void> {
    dirBad = false;
    const r = await ctl.saveSettings({ transfers_dir: path });
    // Zły folder pokazuje komunikat przy wierszu; inne błędy zostają na ogólnej karcie błędu.
    dirBad = r === null && s.error?.key === 'bad_request';
    if (dirBad) s.error = null;
  }

  async function saveKeep(select: HTMLSelectElement): Promise<void> {
    if (!(await ctl.saveSettings({ transfer_keep_days: Number(select.value) }))) {
      select.value = String(s.settings.transfer_keep_days);
    }
  }
</script>

<SettingGroup title={t('settings.group_transfer_copies')}>
  <SettingRow id="transfers_dir" label={t('settings.transfers_dir')} hint={t('settings.transfers_dir_hint')}
    error={dirBad ? t('settings.transfers_dir_bad') : null}>
    <PathPicker value={s.settings.transfers_dir} placeholder={t('settings.transfers_default')} pick={pickDir}
      onchange={saveDir} clearable />
  </SettingRow>
  <SettingRow id="transfer_keep_days" label={t('settings.transfer_keep')} hint={t('settings.transfer_keep_hint')}>
    <select aria-label={t('settings.transfer_keep')} class="field rounded-[10px] px-2.5 py-1.5 text-sm"
      value={String(s.settings.transfer_keep_days)} onchange={(e) => saveKeep(e.currentTarget)}>
      {#each keep as n (n)}<option value={String(n)}>{t('settings.days', { n })}</option>{/each}
    </select>
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_transfer_default')}>
  <SettingRow id="transfer_apps_default" label={t('settings.transfer_apps')} hint={t('settings.transfer_apps_hint')}>
    <Toggle checked={s.settings.transfer_apps_default} label={t('settings.transfer_apps')}
      onchange={async (v) => (await ctl.saveSettings({ transfer_apps_default: v })) !== null} />
  </SettingRow>
  <SettingRow id="verify_copies" label={t('settings.verify')} hint={t('settings.verify_hint')} keywords="bajt hash">
    <Toggle checked={s.settings.verify_copies} label={t('settings.verify')}
      onchange={async (v) => (await ctl.saveSettings({ verify_copies: v })) !== null} />
  </SettingRow>
</SettingGroup>
