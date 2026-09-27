<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import ConfirmDialog from './components/ConfirmDialog.svelte';
  import ErrorCard from './components/ErrorCard.svelte';
  import Header from './components/Header.svelte';
  import StageBar from './components/StageBar.svelte';
  import type { Controller } from './lib/controller';
  import { t } from './lib/i18n/index.svelte';
  import Connect from './screens/Connect.svelte';

  let props: { ctl: Controller } = $props();
  const ctl = untrack(() => props.ctl); // kontroler nie zmienia się przez całe życie okna
  setContext('ctl', ctl);
  const s = ctl.state;
</script>

<div class="flex h-full flex-col">
  <Header />
  <main class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
    {#if s.fatal}
      <ErrorCard fatal />
    {:else}
      <ErrorCard />
      <StageBar />
      <Connect />
    {/if}
  </main>
</div>

{#if s.closeRequested}
  <ConfirmDialog title={t('close.title')} message={t('close.message')} confirm={t('close.confirm')}
    cancel={t('common.cancel')} onconfirm={() => ctl.quit()} oncancel={() => (s.closeRequested = false)} />
{/if}
