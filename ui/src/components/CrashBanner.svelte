<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const id = $derived(s.crashStartup[0]);
</script>

{#if id}
  <Banner tone="warn" icon="triangle-alert" title={t('crash.banner')}>
    {#snippet actions()}
      <Button variant="primary" size="sm" onclick={() => ctl.openCrash(id)}>{t('crash.banner_send')}</Button>
      <Button variant="ghost" size="sm" onclick={() => ctl.discardCrash(id)}>{t('crash.banner_dismiss')}</Button>
    {/snippet}
  </Banner>
{/if}
