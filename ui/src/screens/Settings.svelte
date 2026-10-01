<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { formatGb } from '../lib/logic';
  import type { CacheUsage, Lang, Mode, Theme } from '../lib/types';
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
  const FIELD = 'field min-w-0 flex-1 rounded-xl px-3.5 py-2.5';
  let svc = $state({ name: '', address: '', phone: '', logo: '' });
  let svcSaved = $state(false);

  let limit = $state(String(s.settings.apk_cache_limit_gb));
  let limitBad = $state(false);
  let cache = $state<CacheUsage | null>(null);
  let freed = $state<number | null>(null);
  const gb = (b: number) => formatGb(b, i18n.lang);
  const gbWhole = (b: number) => String(Math.round(b / 1024 ** 3));

  onMount(async () => {
    const [r, c] = await Promise.all([ctl.loadService(), ctl.loadApkCache()]);
    if (r) svc = { name: r.name ?? '', address: r.address ?? '', phone: r.phone ?? '', logo: r.logo ?? '' };
    cache = c;
  });

  async function saveLimit() {
    const n = Number(limit);
    limitBad = !Number.isInteger(n) || n < 1 || (cache !== null && n * 1024 ** 3 > cache.disk_bytes);
    if (limitBad) return;
    const r = await ctl.saveSettings({ apk_cache_limit_gb: n });
    // Błąd walidacji limitu pokazuje komunikat przy polu; inne błędy zostają na ogólnej karcie błędu.
    limitBad = r === null && s.error?.key === 'bad_request';
    if (limitBad) s.error = null;
    if (r) cache = await ctl.loadApkCache();
  }

  async function clearNow() {
    const r = await ctl.clearApkCache();
    if (r) { freed = r.freed_bytes; cache = await ctl.loadApkCache(); }
  }

  async function chooseLogo() {
    const r = await ctl.pickLogo();
    if (r?.path) svc.logo = r.path;
  }

  async function saveService() {
    svcSaved = false;
    const clean = (v: string) => v.trim() || null;
    const r = await ctl.saveService({ name: clean(svc.name), address: clean(svc.address),
                                      phone: clean(svc.phone), logo: clean(svc.logo) });
    svcSaved = r !== null;
  }

  async function checkAdb() {
    const r = await ctl.checkAdb(adbPath.trim() || null);
    if (r) check = r.ok
      ? { ok: true, text: `${t('settings.adb_ok', { version: r.version ?? '' })} · ${t(`settings.adb_source.${r.source}`)}` }
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

    <Card><div class="flex flex-col gap-3 p-6">
      <span class="lbl">{t('settings.mirror_title')}</span>
      <label class="flex items-center gap-3">
        <input type="checkbox" checked={s.settings.mirror_auto}
          onchange={(e) => ctl.saveSettings({ mirror_auto: e.currentTarget.checked })} />
        <span>{t('settings.mirror_auto')}</span>
      </label>
      <span class="text-xs text-mut">{t('settings.mirror_auto_hint')}</span>
    </div></Card>

    <Card><div class="flex flex-col gap-4 p-6">
      <span class="lbl">{t('settings.cache_title')}</span>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="cache-limit">{t('settings.cache_limit')}</label>
        <div class="flex gap-2">
          <input id="cache-limit" type="number" min="1" step="1" class="{FIELD} max-w-[140px]" bind:value={limit} />
          <Button onclick={saveLimit}>{t('settings.cache_save')}</Button>
        </div>
        {#if limitBad}<span class="flex items-center gap-1.5 text-bad"><Icon name="x" />{t('settings.cache_limit_bad')}</span>{/if}
        {#if cache}
          <span class="text-xs text-mut">{t('settings.cache_status', { size: gb(cache.size_bytes), limit: gbWhole(cache.limit_bytes) })}{#if cache.effective_bytes < cache.limit_bytes}{t('settings.cache_status_effective', { effective: gb(cache.effective_bytes), free: gb(cache.free_bytes) })}{/if}</span>
        {/if}
      </div>
      <label class="flex items-center gap-3">
        <input type="checkbox" checked={s.settings.apk_cache_clear_after_repair}
          onchange={(e) => ctl.saveSettings({ apk_cache_clear_after_repair: e.currentTarget.checked })} />
        <span>{t('settings.cache_clear_after')}</span>
      </label>
      <span class="text-xs text-mut">{t('settings.cache_clear_after_hint')}</span>
      <div class="flex items-center gap-3">
        <Button onclick={clearNow} disabled={s.apk.running}>{t('settings.cache_clear_now')}</Button>
        {#if freed !== null}<span class="flex items-center gap-1 text-ok"><Icon name="check" />{t('settings.cache_cleared', { gb: gb(freed) })}</span>{/if}
      </div>
    </div></Card>

    <Card><div class="flex flex-col gap-5 p-6">
      <div class="flex flex-col gap-1">
        <span class="lbl">{t('settings.service_title')}</span>
        <span class="text-xs text-mut">{t('settings.service_hint')}</span>
      </div>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="svc-name">{t('settings.service_name')}</label>
        <input id="svc-name" class={FIELD} bind:value={svc.name} />
      </div>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="svc-address">{t('settings.service_address')}</label>
        <input id="svc-address" class={FIELD} bind:value={svc.address} />
      </div>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="svc-phone">{t('settings.service_phone')}</label>
        <input id="svc-phone" class={FIELD} bind:value={svc.phone} />
      </div>
      <div class="flex flex-col gap-1">
        <label class="font-semibold" for="svc-logo">{t('settings.service_logo')}</label>
        <div class="flex gap-2">
          <input id="svc-logo" class={INPUT} bind:value={svc.logo} />
          <Button onclick={chooseLogo}>{t('settings.choose_logo')}</Button>
        </div>
        <span class="text-xs text-mut">{t('settings.logo_hint')}</span>
      </div>
      <div class="flex items-center gap-3">
        <Button variant="primary" onclick={saveService}>{t('settings.save_service')}</Button>
        {#if svcSaved}<span class="flex items-center gap-1 text-ok"><Icon name="check" />{t('common.saved')}</span>{/if}
      </div>
    </div></Card>
  </div>
</main>
