<script lang="ts">
  // Atrapa kategorii, której wiersz pojawia się dopiero po asynchronicznym odczycie (jak `{#if cache}`).
  import { onMount } from 'svelte';
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';

  let loaded = $state(false);
  onMount(() => { setTimeout(() => { loaded = true; }, 20); });
</script>

<SettingGroup title="Pamięć podręczna APK">
  <SettingRow id="clear_after" label="Czyść po zakończonej naprawie"><i>a</i></SettingRow>
  {#if loaded}<SettingRow id="cache_limit" label="Limit pamięci podręcznej"><i>b</i></SettingRow>{/if}
</SettingGroup>
