<script lang="ts">
  import { createSettingsSearch } from './search.svelte';
  import SettingGroup from './SettingGroup.svelte';
  import SettingRow from './SettingRow.svelte';
  const search = createSettingsSearch();
</script>

<input aria-label="q" oninput={(e) => (search.query = e.currentTarget.value)} />
<SettingGroup title="Grupa">
  <SettingRow id="a" label="Źródło adb" hint="podpowiedź"><i>x</i></SettingRow>
  <SettingRow id="b" label="Folder" keywords="pdf"><i>y</i></SettingRow>
</SettingGroup>
