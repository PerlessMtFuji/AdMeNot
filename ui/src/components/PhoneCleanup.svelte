<script lang="ts">
  // Przywracanie ustawień telefonu po przerwanym wgrywaniu (`phone_cleanup`). Most ponawia nieudane
  // sprzątanie sam, więc bez przycisku ponowienia; powtórzone niepowodzenie to wciąż ten jeden baner.
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import TapPrompt, { smsAppName } from './TapPrompt.svelte';

  const s = getContext<Controller>('ctl').state;
  const c = $derived(s.transfer.cleanup);
</script>

{#if c.running}
  <Banner tone="warn" icon="rotate-ccw" title={t('transfer.restore.cleanup.running')}>
    {t('transfer.restore.cleanup.running_text')}
  </Banner>
  <TapPrompt />
{:else if c.ok === false}
  <Banner tone="bad" icon="triangle-alert" title={t('transfer.restore.cleanup.failed')}>
    {t('transfer.restore.cleanup.failed_text', { app: smsAppName(s.transfer.restore.tapPackage) })}
  </Banner>
{/if}
