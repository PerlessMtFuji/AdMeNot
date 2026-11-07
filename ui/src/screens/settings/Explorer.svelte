<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import PathPicker from '../../components/settings/PathPicker.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t, tp } from '../../lib/i18n/index.svelte';
  import type { Settings } from '../../lib/types';
  import Button from '../../ui/Button.svelte';
  import Segmented from '../../ui/Segmented.svelte';
  import Toggle from '../../ui/Toggle.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  type ViewChoice = 'auto' | 'list' | 'grid';
  type DestMode = Settings['explorer_dest_mode'];

  const views = $derived((['auto', 'list', 'grid'] as ViewChoice[])
    .map((value) => ({ value, label: t(`settings.view_${value}`) })));
  const modes = $derived((['last', 'fixed', 'ask'] as DestMode[])
    .map((value) => ({ value, label: t(`settings.dest_${value}`) })));

  const view = $derived<ViewChoice>(s.settings.explorer_view ?? 'auto');
  const phones = $derived(s.settings.explorer_recent_phones);

  onMount(() => { void ctl.loadExplorerRecents(); }); // „Ostatnio” zapisane w eksploratorze po starcie

  const saveView = (v: ViewChoice) => ctl.saveSettings({ explorer_view: v === 'auto' ? null : v });

  const pickFolder = async () => (await ctl.pickFolder())?.path ?? null;

  // „Stały” bez ustawionego folderu od razu pyta o folder; anulowanie zostawia poprzedni tryb.
  async function chooseMode(mode: DestMode): Promise<void> {
    if (mode === 'fixed' && !s.settings.explorer_dest_fixed) {
      const path = await pickFolder();
      if (path === null) return;
      await ctl.saveSettings({ explorer_dest_mode: mode, explorer_dest_fixed: path });
      return;
    }
    await ctl.saveSettings({ explorer_dest_mode: mode });
  }
</script>

<SettingGroup title={t('settings.group_explorer_view')}>
  <SettingRow id="explorer_view" label={t('settings.explorer_view')} hint={t('settings.explorer_view_hint')} keywords="lista siatka">
    <Segmented label={t('settings.explorer_view')} value={view} options={views} onchange={saveView} />
  </SettingRow>
  <SettingRow id="explorer_peek" label={t('settings.explorer_peek')} keywords="podglad">
    <Toggle checked={s.settings.explorer_peek ?? true} label={t('settings.explorer_peek')}
      onchange={async (v) => (await ctl.saveSettings({ explorer_peek: v })) !== null} />
  </SettingRow>
  <SettingRow id="explorer_hidden" label={t('settings.explorer_hidden')} hint={t('settings.explorer_hidden_hint')}>
    <Toggle checked={s.settings.explorer_hidden} label={t('settings.explorer_hidden')}
      onchange={async (v) => (await ctl.saveSettings({ explorer_hidden: v })) !== null} />
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_explorer_copy')}>
  <SettingRow id="explorer_dest_mode" label={t('settings.dest')}>
    <Segmented label={t('settings.dest')} value={s.settings.explorer_dest_mode} options={modes} onchange={chooseMode} />
  </SettingRow>
  {#if s.settings.explorer_dest_mode === 'fixed'}
    <SettingRow id="explorer_dest_fixed" label={t('settings.dest_fixed_folder')} dependent>
      <PathPicker value={s.settings.explorer_dest_fixed} placeholder={t('settings.dest_fixed_unset')} pick={pickFolder}
        onchange={(v) => ctl.saveSettings({ explorer_dest_fixed: v })} />
    </SettingRow>
  {/if}
  <SettingRow id="verify_copies_explorer" label={t('settings.verify')} hint={t('settings.verify_same_hint')} keywords="bajt hash">
    <Toggle checked={s.settings.verify_copies} label={t('settings.verify')}
      onchange={async (v) => (await ctl.saveSettings({ verify_copies: v })) !== null} />
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.group_explorer_history')}>
  <SettingRow id="explorer_recents" label={t('settings.recents')} hint={phones > 0 ? tp('settings.recents_phones', phones) : t('settings.recents_none')}>
    <Button size="sm" disabled={phones === 0} onclick={() => ctl.clearExplorerRecents()}>{t('settings.recents_clear')}</Button>
  </SettingRow>
</SettingGroup>
