<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import ConfirmDialog from './components/ConfirmDialog.svelte';
  import Console from './components/Console.svelte';
  import ErrorCard from './components/ErrorCard.svelte';
  import Header from './components/Header.svelte';
  import StageBar from './components/StageBar.svelte';
  import type { Controller } from './lib/controller';
  import { t } from './lib/i18n/index.svelte';
  import Connect from './screens/Connect.svelte';
  import Execute from './screens/Execute.svelte';
  import History from './screens/History.svelte';
  import Results from './screens/Results.svelte';
  import Settings from './screens/Settings.svelte';

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
      {#if s.screen === 'history'}
        <History />
      {:else if s.screen === 'settings'}
        <Settings />
      {:else}
        <StageBar />
        {#if s.phase === 'connect' || (s.phase === 'scanning' && !s.device)}
          <Connect />
        {:else if s.phase === 'executing' || s.phase === 'done'}
          <Execute />
        {:else}
          <Results />
        {/if}
      {/if}
    {/if}
  </main>
  {#if s.settings.mode === 'expert' && s.consoleOpen}
    <Console />
  {/if}
</div>

{#if s.closeRequested}
  <ConfirmDialog title={t('close.title')} message={t('close.message')} confirm={t('close.confirm')}
    cancel={t('common.cancel')} onconfirm={() => ctl.quit()} oncancel={() => (s.closeRequested = false)} />
{/if}
