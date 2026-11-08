<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { shownChecks } from '../lib/logic';
  import SiteNotifications from './SiteNotifications.svelte';

  // Ponawianie odczytu Firefoxa żyje w ekranie Naprawa (Results), bo licznik zakładki „Telefon” ma się
  // odświeżać także wtedy, gdy ta sekcja jest odmontowana (spec układu Naprawy §8a.5).
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const checks = $derived(shownChecks(s.scan));
</script>

{#if checks.length}
  <!-- Każda kontrola to własna zwijana karta; sekcja tylko je grupuje. -->
  <section aria-label={t('checks.title')} class="flex flex-col gap-2.5">
    {#each checks as c (c.id)}
      {#if c.id === 'site_notifications'}<SiteNotifications check={c} />{/if}
    {/each}
  </section>
{/if}
