<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
</script>

<Banner tone="warn" icon="triangle-alert" title={t('welcome.risk_title')}>
  <ul class="ml-4 list-disc space-y-1">
    {#each [1, 2, 3, 4, 5] as n (n)}<li>{t(`welcome.risk${n}`)}</li>{/each}
  </ul>
</Banner>
