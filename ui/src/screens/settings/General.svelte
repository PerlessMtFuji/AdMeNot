<script lang="ts">
  import { getContext } from 'svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Lang, Mode, Theme } from '../../lib/types';
  import Segmented from '../../ui/Segmented.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  const themes = $derived([
    { value: 'system' as Theme, label: t('settings.theme_system') },
    { value: 'light' as Theme, label: t('settings.theme_light') },
    { value: 'dark' as Theme, label: t('settings.theme_dark') },
  ]);
  const langs: { value: Lang; label: string }[] = [{ value: 'pl', label: 'Polski' }, { value: 'en', label: 'English' }];
  const modes = $derived([
    { value: 'simple' as Mode, label: t('settings.mode_simple') },
    { value: 'expert' as Mode, label: t('settings.mode_expert') },
  ]);
</script>

<SettingGroup title={t('settings.appearance')}>
  <SettingRow id="theme" label={t('settings.theme')}>
    <Segmented label={t('settings.theme')} value={s.settings.theme} options={themes} onchange={(v) => ctl.setTheme(v)} />
  </SettingRow>
  <SettingRow id="lang" label={t('settings.lang')}>
    <Segmented label={t('settings.lang')} value={s.settings.lang} options={langs} onchange={(v) => ctl.setLang(v)} />
  </SettingRow>
  <SettingRow id="mode" label={t('settings.mode')} hint={t('settings.mode_hint')}>
    <Segmented label={t('settings.mode')} value={s.settings.mode} options={modes} onchange={(v) => ctl.setMode(v)} />
  </SettingRow>
</SettingGroup>
