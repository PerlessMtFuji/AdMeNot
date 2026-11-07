<script lang="ts">
  // Atrapa kategorii „Ogólne” w testach szkieletu ekranu (prawdziwe wiersze dochodzą w kolejnych zadaniach).
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
</script>

<SettingGroup title="Wygląd">
  <SettingRow id="theme" label="Motyw"><i>x</i></SettingRow>
  <SettingRow id="lang" label="Język"><i>y</i></SettingRow>
</SettingGroup>
