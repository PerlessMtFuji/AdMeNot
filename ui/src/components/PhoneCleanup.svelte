<script lang="ts">
  // Przywracanie ustawień telefonu po przerwanym wgrywaniu (`phone_cleanup`). Most ponawia nieudane
  // sprzątanie sam (najwyżej 3 razy na podłączenie), więc bez przycisku ponowienia; powtórzone
  // niepowodzenie to wciąż ten jeden czerwony baner, także w czasie ponowienia w tle.
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { cleanupBanner } from '../lib/logic';
  import Banner from '../ui/Banner.svelte';
  import TapPrompt, { smsAppName } from './TapPrompt.svelte';

  const s = getContext<Controller>('ctl').state;
  const c = $derived(s.transfer.cleanup);
  const banner = $derived(cleanupBanner(c, s.serial));
</script>

{#if banner === 'running'}
  <Banner tone="warn" icon="rotate-ccw" title={t('transfer.restore.cleanup.running')}>
    {t('transfer.restore.cleanup.running_text')}
  </Banner>
  <TapPrompt />
{:else if banner === 'failed'}
  <Banner tone="bad" icon="triangle-alert" title={t('transfer.restore.cleanup.failed')}>
    {t('transfer.restore.cleanup.failed_text', { app: smsAppName(s.transfer.restore.tapPackage) })}
  </Banner>
  {#if c.running}<TapPrompt />{/if}
{/if}
