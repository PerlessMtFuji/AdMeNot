<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import ConfirmDialog from './components/ConfirmDialog.svelte';
  import ErrorCard from './components/ErrorCard.svelte';
  import type { Controller } from './lib/controller';
  import { t } from './lib/i18n/index.svelte';
  import Connect from './screens/Connect.svelte';
  import Execute from './screens/Execute.svelte';
  import History from './screens/History.svelte';
  import Results from './screens/Results.svelte';
  import Settings from './screens/Settings.svelte';
  import AppShell from './ui/AppShell.svelte';

  let props: { ctl: Controller } = $props();
  const ctl = untrack(() => props.ctl); // kontroler nie zmienia się przez całe życie okna
  setContext('ctl', ctl);
  const s = ctl.state;
</script>

<AppShell>
  {#if s.fatal}
    <div class="flex-1 p-6"><ErrorCard fatal /></div>
  {:else if s.screen === 'history'}
    <History />
  {:else if s.screen === 'settings'}
    <Settings />
  {:else if s.phase === 'connect' || s.phase === 'scanning'}
    <Connect />
  {:else if s.phase === 'executing' || s.phase === 'done'}
    <Execute />
  {:else}
    <Results />
  {/if}
</AppShell>

{#if s.closeRequested}
  <ConfirmDialog title={t('close.title')} message={t('close.message')} confirm={t('close.confirm')}
    cancel={t('common.cancel')} onconfirm={() => ctl.quit()} oncancel={() => (s.closeRequested = false)} />
{/if}
