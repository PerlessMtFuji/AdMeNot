<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { shownChecks } from '../lib/logic';
  import SiteNotifications from './SiteNotifications.svelte';

  // Odczyt Firefoxa przez zdalne debugowanie pojawia się, gdy serwisant je włączy na telefonie: bez przycisku
  // ponowienia program sam sprawdza co kilka sekund, dopóki sekcja jest na ekranie i podpowiedź jest prawdziwa.
  // Tanio: telefon czyta tylko gniazdo debugowania, pełny odczyt witryn dopiero po jego pojawieniu się.
  const RECHECK_MS = 5000;

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const checks = $derived(shownChecks(s.scan));
  const waitingForRdp = $derived(checks.some((c) => c.browsers.some((b) => b.rdp_hint)));

  $effect(() => {
    if (!waitingForRdp) return;
    const id = setInterval(() => void ctl.recheckSiteNotifications(true), RECHECK_MS);
    return () => clearInterval(id);
  });
</script>

{#if checks.length}
  <!-- Każda kontrola to własna zwijana karta; sekcja tylko je grupuje. -->
  <section aria-label={t('checks.title')} class="flex flex-col gap-2.5">
    {#each checks as c (c.id)}
      {#if c.id === 'site_notifications'}<SiteNotifications check={c} />{/if}
    {/each}
  </section>
{/if}
