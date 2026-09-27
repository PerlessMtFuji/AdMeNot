<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';

  let { orders }: { orders: string[] } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  async function undo(order: string) {
    await ctl.openHistory();
    await ctl.undo(order);
  }
</script>

{#each orders as order (order)}
  <Banner tone="warn" icon="triangle-alert"
    title={s.disconnectedOrder === order ? t('interrupted.disconnected', { order }) : t('interrupted.text', { order })}>
    {#snippet actions()}
      <Button variant="ghost" size="sm" disabled={s.orderRunning} onclick={() => undo(order)}>{t('interrupted.undo')}</Button>
      <Button variant="primary" size="sm" disabled={s.orderRunning} onclick={() => ctl.resume(order)}>{t('interrupted.resume')}</Button>
    {/snippet}
  </Banner>
{/each}
