<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import type { AppView } from '../lib/types';

  let props: { app: AppView } = $props();
</script>

<div class="evidence mt-1.5">
  {#each props.app.findings as f (f.rule_id)}
    <div><b class="font-normal text-[#93c5fd]">{f.rule_id}</b> +{f.weight} · {f.text_expert}</div>
    {#if Object.keys(f.evidence).length}
      <div class="opacity-70">{JSON.stringify(f.evidence)}</div>
    {/if}
  {/each}
  {#if props.app.ad_sdks?.length}
    <div>{t('expert.ad_sdks', { list: props.app.ad_sdks.join(', ') })}</div>
  {/if}
  {#if props.app.apk_error}
    <div>{t('expert.apk_error')}: {props.app.apk_error}</div>
  {/if}
</div>
