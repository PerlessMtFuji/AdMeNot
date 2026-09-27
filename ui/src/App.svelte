<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import ErrorCard from './components/ErrorCard.svelte';
  import type { Controller } from './lib/controller';
  import { t } from './lib/i18n/index.svelte';
  import Connect from './screens/Connect.svelte';
  import Execute from './screens/Execute.svelte';
  import History from './screens/History.svelte';
  import Results from './screens/Results.svelte';
  import Scan from './screens/Scan.svelte';
  import Settings from './screens/Settings.svelte';
  import AppShell from './ui/AppShell.svelte';
  import Button from './ui/Button.svelte';
  import Dialog from './ui/Dialog.svelte';

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
  {:else if s.phase === 'connect'}
    <Connect />
  {:else if s.phase === 'scanning'}
    <Scan />
  {:else if s.phase === 'executing' || s.phase === 'done'}
    <Execute />
  {:else}
    <Results />
  {/if}
</AppShell>

{#if s.closeRequested}
  <Dialog title={t('close.title')} oncancel={() => (s.closeRequested = false)}>
    {t('close.message')}
    {#snippet actions()}
      <Button onclick={() => (s.closeRequested = false)}>{t('common.cancel')}</Button>
      <Button variant="danger" onclick={() => ctl.quit()}>{t('close.confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}
