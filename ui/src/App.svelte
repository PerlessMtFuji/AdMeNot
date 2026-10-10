<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import CrashDialog from './components/CrashDialog.svelte';
  import ErrorCard from './components/ErrorCard.svelte';
  import type { Controller } from './lib/controller';
  import { t } from './lib/i18n/index.svelte';
  import { needsWelcome } from './lib/logic';
  import { screenIn } from './lib/motion';
  import Connect from './screens/Connect.svelte';
  import Execute from './screens/Execute.svelte';
  import History from './screens/History.svelte';
  import Results from './screens/Results.svelte';
  import Scan from './screens/Scan.svelte';
  import Settings from './screens/Settings.svelte';
  import Welcome from './screens/Welcome.svelte';
  import AppShell from './ui/AppShell.svelte';
  import Button from './ui/Button.svelte';
  import Dialog from './ui/Dialog.svelte';
  import UpdateDialog from './components/UpdateDialog.svelte';

  let props: { ctl: Controller } = $props();
  const ctl = untrack(() => props.ctl); // kontroler nie zmienia się przez całe życie okna
  setContext('ctl', ctl);
  const s = ctl.state;
  // Ostrzeżenie przy pierwszym starcie (spec kroku H §3.1): zamiast zwykłego widoku, bez panelu kroków.
  const welcome = $derived(s.settingsLoaded && needsWelcome(s.settings));

  const ORDER = ['connect', 'scanning', 'results', 'executing', 'history', 'settings', 'fatal'];
  const view = $derived(s.fatal ? 'fatal' : s.screen !== 'main' ? s.screen
    : s.phase === 'done' ? 'executing' : s.phase);
  let last = 'connect';
  let dir = $state<1 | -1>(1);
  $effect.pre(() => {
    const next = view;
    dir = ORDER.indexOf(next) >= ORDER.indexOf(last) ? 1 : -1;
    last = next;
  });
</script>

{#if welcome}
  <Welcome />
{:else}
<AppShell>
  {#key view}
    <div class="flex min-h-0 min-w-0 flex-1" in:screenIn={{ dir }}>
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
    </div>
  {/key}
</AppShell>
{/if}

{#if s.closeRequested}
  <Dialog title={t('close.title')} oncancel={() => (s.closeRequested = false)}>
    {t('close.message')}
    {#snippet actions()}
      <Button onclick={() => (s.closeRequested = false)}>{t('common.cancel')}</Button>
      <Button variant="danger" onclick={() => ctl.quit()}>{t('close.confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}

{#if !welcome}  <!-- aktualizacje i raporty awarii czekają na zamknięcie ekranu powitalnego -->
  <UpdateDialog />
  <CrashDialog />
{/if}
