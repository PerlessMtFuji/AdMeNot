<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { formatGb } from '../lib/logic';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const gb = (b: number) => formatGb(b, i18n.lang);
  const RESERVE = 2 * 1024 ** 3;
  const e = $derived(s.apkEstimate);
  const q = $derived(s.apkQuestion);
  const apk = $derived(s.scan?.apk ?? null);
</script>

{#if s.apk.running && e}
  <p class="text-sm text-mut">
    {t('apk_cache.estimate', { gb: gb(e.to_fetch_bytes), apps: e.apps })}{#if e.unknown} {t('apk_cache.unknown', { count: e.unknown })}{/if}.
    {#if e.to_fetch_bytes > e.effective_bytes}{t('apk_cache.over', { gb: gb(e.effective_bytes) })}{/if}
  </p>
{/if}
{#if q}
  <Banner tone="warn" icon="info" title={t('apk_cache.question_title')}>
    {t('apk_cache.question_text', { free: gb(q.free_bytes), need: gb(q.largest_bytes + RESERVE) })}
    {#snippet actions()}
      <Button size="sm" onclick={() => ctl.answerApk('skip')}>{t('apk_cache.skip')}</Button>
      <Button size="sm" onclick={() => ctl.answerApk('run')}>{t('apk_cache.run')}</Button>
      <Button size="sm" variant="primary" onclick={() => ctl.answerApk('clear')}>{t('apk_cache.clear')}</Button>
    {/snippet}
  </Banner>
{/if}
{#if apk?.stopped_no_space && !s.apk.running}
  <Banner tone="warn" icon="info" title={t('apk_cache.stopped', { done: apk.analyzed, total: apk.requested })} />
{/if}
