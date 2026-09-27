<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { Lang, Mode, Theme } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Icon from '../ui/Icon.svelte';
  import Segmented from '../ui/Segmented.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let adbPath = $state(s.settings.adb_path ?? '');
  let backups = $state(s.settings.backups_dir ?? '');
  let check = $state<{ ok: boolean; text: string } | null>(null);
  let saved = $state(false);
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
  const INPUT = 'field mono min-w-0 flex-1 rounded-xl px-3.5 py-2.5';

  async function checkAdb() {
    const r = await ctl.checkAdb(adbPath.trim() || null);
    if (r) check = r.ok
      ? { ok: true, text: t('settings.adb_ok', { version: r.version ?? '' }) }
      : { ok: false, text: t('settings.adb_fail', { message: r.message }) };
  }

  async function choose() {
    const r = await ctl.pickFolder();
    if (r?.path) backups = r.path;
  }

  async function savePaths() {
    saved = false;
    const r = await ctl.saveSettings({ adb_path: adbPath.trim() || null, backups_dir: backups.trim() || null });
    saved = r !== null;
  }
</script>

<main class="min-w-0 flex-1 scroll-fade overflow-auto px-7 py-7">
  <div class="mx-auto flex max-w-[760px] flex-col gap-4">
    <h1 class="text-2xl font-extrabold">{t('settings.title')}</h1>

    <Card><div class="flex flex-col gap-5 p-6">
      <span class="lbl">{t('settings.appearance')}</span>
      <div class="flex items-center justify-between gap-4"><span>{t('settings.theme')}</span>
        <Segmented label={t('settings.theme')} value={s.settings.theme} options={themes} onchange={(v) => ctl.setTheme(v)} /></div>
      <div class="flex items-center justify-between gap-4"><span>{t('settings.lang')}</span>
        <Segmented label={t('settings.lang')} value={s.settings.lang} options={langs} onchange={(v) => ctl.setLang(v)} /></div>
      <div class="flex items-center justify-between gap-4"><span>{t('settings.mode')}</span>
        <Segmented label={t('settings.mode')} value={s.settings.mode} options={modes} onchange={(v) => ctl.setMode(v)} /></div>
    </div></Card>

    <Card><div class="flex flex-col gap-5 p-6">
      <span class="lbl">{t('settings.paths')}</span>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="adb-path">{t('settings.adb')}</label>
        <div class="flex gap-2">
          <input id="adb-path" class={INPUT} bind:value={adbPath} placeholder="C:\platform-tools\adb.exe" />
          <Button onclick={checkAdb}>{t('settings.check')}</Button>
        </div>
        <span class="text-xs text-mut">{t('settings.adb_hint')}</span>
        {#if check}<span class="flex items-center gap-1.5 {check.ok ? 'text-ok' : 'text-bad'}"><Icon name={check.ok ? 'check' : 'x'} />{check.text}</span>{/if}
      </div>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="backups-dir">{t('settings.backups')}</label>
        <div class="flex gap-2">
          <input id="backups-dir" class={INPUT} bind:value={backups} />
          <Button onclick={choose}>{t('settings.choose')}</Button>
        </div>
        <span class="text-xs text-mut">{t('settings.backups_hint')}</span>
      </div>
      <div class="flex items-center gap-3">
        <Button variant="primary" onclick={savePaths}>{t('common.save')}</Button>
        {#if saved}<span class="flex items-center gap-1 text-ok"><Icon name="check" />{t('common.saved')}</span>{/if}
      </div>
    </div></Card>

    <p class="text-xs text-mut">{t('settings.service_soon')}</p>
  </div>
</main>
