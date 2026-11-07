<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import PathPicker from '../../components/settings/PathPicker.svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
  import type { Controller } from '../../lib/controller';
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import { formatGb, LEVEL_TONE } from '../../lib/logic';
  import type { ApkModeDefault, CacheCleared, CacheUsage, Level } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Progress from '../../ui/Progress.svelte';
  import Segmented from '../../ui/Segmented.svelte';
  import Toggle from '../../ui/Toggle.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  const levels = $derived((['silence', 'disable', 'remove'] as Level[])
    .map((value) => ({ value, label: t(`choice.${value}`), tone: LEVEL_TONE[value] })));
  const apkModes = $derived((['ask', 'full', 'manual'] as ApkModeDefault[])
    .map((value) => ({ value, label: t(`settings.apk_mode_${value}`) })));

  const GB = 1024 ** 3;
  const STEPS = [1, 2, 3, 5, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 500, 1000, 2000];

  let cache = $state<CacheUsage | null>(null);
  let cleared = $state<CacheCleared | null>(null);
  let limitBad = $state(false);
  const gb = (b: number) => formatGb(b, i18n.lang);
  const gbWhole = (b: number) => String(Math.round(b / GB));

  // Lista limitów: od 1 GB do pojemności dysku (po wczytaniu pamięci podręcznej) oraz zapisany limit.
  const limits = $derived.by(() => {
    const max = cache ? Math.floor(cache.disk_bytes / GB) : 0;
    const all = new Set([...STEPS.filter((n) => n <= max), s.settings.apk_cache_limit_gb]);
    return [...all].sort((a, b) => a - b);
  });
  const usage = $derived(cache && cache.limit_bytes > 0 ? cache.size_bytes / cache.limit_bytes : 0);

  onMount(async () => { cache = await ctl.loadApkCache(); });

  async function saveLimit(select: HTMLSelectElement): Promise<void> {
    limitBad = false;
    const r = await ctl.saveSettings({ apk_cache_limit_gb: Number(select.value) });
    // Błąd walidacji limitu pokazuje komunikat przy wierszu; inne błędy zostają na ogólnej karcie błędu.
    limitBad = r === null && s.error?.key === 'bad_request';
    if (limitBad) s.error = null;
    if (r) cache = await ctl.loadApkCache();
    else select.value = String(s.settings.apk_cache_limit_gb);
  }

  async function clearNow(): Promise<void> {
    const r = await ctl.clearApkCache();
    if (r) { cleared = r; cache = await ctl.loadApkCache(); }
  }

  const pickBackups = async () => (await ctl.pickFolder())?.path ?? null;
  const saveBackups = (v: string | null) => ctl.saveSettings({ backups_dir: v });
</script>

<SettingGroup title={t('settings.group_scan')}>
  <SettingRow id="apk_mode_default" label={t('settings.apk_mode_default')} hint={t('settings.apk_mode_hint')} keywords="apk">
    <Segmented label={t('settings.apk_mode_default')} value={s.settings.apk_mode_default} options={apkModes}
      onchange={(v) => ctl.saveSettings({ apk_mode_default: v })} />
  </SettingRow>
  <SettingRow id="select_level" label={t('settings.select_level')} hint={t('settings.select_level_hint')}>
    <Segmented label={t('settings.select_level')} value={s.settings.select_level} options={levels}
      onchange={(v) => ctl.saveSettings({ select_level: v })} />
  </SettingRow>
  <SettingRow id="mirror_auto" label={t('settings.mirror_auto')} hint={t('settings.mirror_auto_hint')}>
    <Toggle checked={s.settings.mirror_auto} label={t('settings.mirror_auto')}
      onchange={async (v) => (await ctl.saveSettings({ mirror_auto: v })) !== null} />
  </SettingRow>
</SettingGroup>

<SettingGroup title={t('settings.cache_title')}>
  <SettingRow id="cache_limit" label={cache ? t('settings.cache_usage', { size: gb(cache.size_bytes), limit: gbWhole(cache.limit_bytes) }) : t('settings.cache_limit')}
    hint={cache ? t('settings.cache_status', { size: gb(cache.size_bytes), limit: gbWhole(cache.limit_bytes) })
      + (cache.effective_bytes < cache.limit_bytes ? t('settings.cache_status_effective', { effective: gb(cache.effective_bytes), free: gb(cache.free_bytes) }) : '') : undefined}
    keywords={`${t('settings.cache_limit')} ${t('settings.cache_title')}`} error={limitBad ? t('settings.cache_limit_bad') : null}>
    {#if cache}<div class="w-24 flex-none"><Progress value={usage} label={t('settings.cache_title')} /></div>{/if}
    <select aria-label={t('settings.cache_limit')} class="field rounded-[10px] px-2.5 py-1.5 text-sm" value={String(s.settings.apk_cache_limit_gb)}
      onchange={(e) => saveLimit(e.currentTarget)}>
      {#each limits as n (n)}<option value={String(n)}>{t('settings.gb', { n })}</option>{/each}
    </select>
    <Button size="sm" onclick={clearNow} disabled={s.apk.running}>{t('settings.cache_clear_now')}</Button>
  </SettingRow>
  <SettingRow id="clear_after" label={t('settings.cache_clear_after')} hint={t('settings.cache_clear_after_hint')}>
    <Toggle checked={s.settings.apk_cache_clear_after_repair} label={t('settings.cache_clear_after')}
      onchange={async (v) => (await ctl.saveSettings({ apk_cache_clear_after_repair: v })) !== null} />
  </SettingRow>
  {#if cleared !== null}
    <div class="flex flex-col gap-2 border-t border-line px-4 py-2.5">
      <Banner tone="ok" icon="check">{t('settings.cache_cleared', { gb: gb(cleared.freed_bytes) })}</Banner>
      {#if cleared.left_bytes > 0}
        <Banner tone="info" icon="info">{t('settings.cache_left', { gb: gb(cleared.left_bytes) })}</Banner>
      {/if}
    </div>
  {/if}
</SettingGroup>

<SettingGroup title={t('settings.group_backups')}>
  <SettingRow id="backups_dir" label={t('settings.backups')} hint={t('settings.backups_hint')} keywords="apk">
    <PathPicker value={s.settings.backups_dir} placeholder={t('settings.backups_default')} pick={pickBackups}
      onchange={saveBackups} clearable />
  </SettingRow>
</SettingGroup>
