<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
</script>

{#if s.donateBanner}
  <Banner tone="info" icon="heart">
    {t('donate.banner')}
    {#snippet actions()}
      <Button variant="ghost" size="sm" onclick={() => { ctl.closeDonate(); void ctl.setDonateReminders(false); }}>{t('donate.already')}</Button>
      <Button variant="primary" size="sm" onclick={() => { ctl.closeDonate(); void ctl.openDonate(); }}>{t('donate.support')}</Button>
      <Button variant="ghost" size="icon" label={t('donate.close')} title={t('donate.close')}
        onclick={() => ctl.closeDonate()}><Icon name="x" /></Button>
    {/snippet}
  </Banner>
{/if}
