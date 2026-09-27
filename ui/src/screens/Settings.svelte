<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { Lang } from '../lib/types';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const LANGS: { value: Lang; name: string }[] = [
    { value: 'pl', name: 'Polski' },
    { value: 'en', name: 'English' },
  ];
  let adbPath = $state(s.settings.adb_path ?? '');
  let backups = $state(s.settings.backups_dir ?? '');
  let check = $state<{ ok: boolean; text: string } | null>(null);
  let saved = $state(false);

  async function checkAdb() {
    const r = await ctl.checkAdb(adbPath.trim() || null);
    if (r) {
      check = r.ok
        ? { ok: true, text: t('settings.adb_ok', { version: r.version ?? '' }) }
        : { ok: false, text: t('settings.adb_fail', { message: r.message }) };
    }
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

<section class="card hard flex max-w-[680px] flex-col gap-4">
  <b class="text-[14px]">{t('settings.title')}</b>

  <fieldset>
    <legend class="lbl mb-1">{t('settings.lang')}</legend>
    {#each LANGS as lang (lang.value)}
      <label class="mr-4 inline-flex items-center gap-1.5">
        <input type="radio" name="lang" checked={s.settings.lang === lang.value}
          onchange={() => ctl.setLang(lang.value)} /> {lang.name}
      </label>
    {/each}
  </fieldset>

  <fieldset>
    <legend class="lbl mb-1">{t('settings.mode')}</legend>
    <label class="mr-4 inline-flex items-center gap-1.5">
      <input type="radio" name="mode" checked={s.settings.mode === 'simple'} onchange={() => ctl.setMode('simple')} />
      {t('settings.mode_simple')}
    </label>
    <label class="inline-flex items-center gap-1.5">
      <input type="radio" name="mode" checked={s.settings.mode === 'expert'} onchange={() => ctl.setMode('expert')} />
      {t('settings.mode_expert')}
    </label>
  </fieldset>

  <div class="flex flex-col gap-1">
    <label class="lbl" for="adb-path">{t('settings.adb')}</label>
    <div class="flex gap-2">
      <input id="adb-path" class="mono flex-1 rounded border border-line bg-card px-2 py-1.5" bind:value={adbPath}
        placeholder="C:\platform-tools\adb.exe" />
      <button class="btn" onclick={checkAdb}>{t('settings.check')}</button>
    </div>
    <span class="text-[11px] text-mut">{t('settings.adb_hint')}</span>
    {#if check}<span class={check.ok ? 'ok' : 'bad'}>{check.text}</span>{/if}
  </div>

  <div class="flex flex-col gap-1">
    <label class="lbl" for="backups-dir">{t('settings.backups')}</label>
    <div class="flex gap-2">
      <input id="backups-dir" class="mono flex-1 rounded border border-line bg-card px-2 py-1.5" bind:value={backups} />
      <button class="btn" onclick={choose}>{t('settings.choose')}</button>
    </div>
    <span class="text-[11px] text-mut">{t('settings.backups_hint')}</span>
  </div>

  <div class="flex items-center gap-2">
    <button class="btn btn-pri" onclick={savePaths}>{t('common.save')}</button>
    {#if saved}<span class="ok">✓ {t('common.saved')}</span>{/if}
  </div>

  <p class="text-[11px] text-mut">{t('settings.service_soon')}</p>
</section>
