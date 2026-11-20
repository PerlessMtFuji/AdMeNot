<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import type { AppView } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  // Obca aplikacja ustawiona jako ekran główny: adware chowa ikonę, więc etykieta stoi przy nazwie
  // w każdym widoku listy, niezależnie od werdyktu (zgłoszenie 2026-11-20).
  let { app }: { app: AppView } = $props();
</script>

{#if app.is_home && !app.is_system}
  <span class="flex-none" title={t('results.home_title')}>
    <Pill tone="warn"><span class="inline-flex items-center gap-1"><Icon name="house" size={12} strokeWidth={2.5} />{t('results.home')}</span></Pill>
  </span>
{/if}
