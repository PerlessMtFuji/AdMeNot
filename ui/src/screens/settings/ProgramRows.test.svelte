<script lang="ts">
  // Atrapa kategorii „Program” w testach szkieletu ekranu.
  import SettingGroup from '../../components/settings/SettingGroup.svelte';
  import SettingRow from '../../components/settings/SettingRow.svelte';
</script>

<SettingGroup title="Zaawansowane">
  <SettingRow id="adb_path" label="Ścieżka do adb.exe" keywords="adb platform-tools"><i>z</i></SettingRow>
</SettingGroup>
