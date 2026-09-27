<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';

  let props: { orders: string[] } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;

  async function undo(order: string) {
    await ctl.openHistory();
    await ctl.undo(order);
  }
</script>

{#each props.orders as order (order)}
  <div class="card flex flex-wrap items-center gap-2 border-[var(--warn-line)] bg-[var(--warn-bg)]" role="status">
    <span class="warn">⚠</span>
    <span>{s.disconnectedOrder === order
      ? t('interrupted.disconnected', { order })
      : t('interrupted.text', { order })}</span>
    <span class="ml-auto flex gap-3">
      <button class="btn-link" disabled={s.orderRunning} onclick={() => ctl.resume(order)}>{t('interrupted.resume')}</button>
      <button class="btn-link" disabled={s.orderRunning} onclick={() => undo(order)}>{t('interrupted.undo')}</button>
    </span>
  </div>
{/each}
