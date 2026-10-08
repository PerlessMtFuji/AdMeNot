<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { updateBanner } from '../lib/logic';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const kind = $derived(updateBanner(s.update, s.updatedSeen));
  const u = $derived(s.update);
  // Instalator zamyka adb — nigdy w trakcie skanu, analizy ani zlecenia (spec aktualizacji §7).
  const busy = $derived(s.job !== null);
</script>

{#snippet install()}
  <Button variant="primary" size="sm" disabled={busy} title={busy ? t('update.busy') : undefined}
    onclick={() => ctl.openUpdate()}>{t('update.install')}</Button>
{/snippet}

{#if kind === 'retired' && u?.retired}
  <Banner tone="bad" icon="shield-alert" title={t('update.retired_title')}>
    {u.retired.reason ? t('update.retired_reason', { reason: u.retired.reason }) : ''}{t('update.retired_text')}
    {#snippet actions()}
      {#if u.available}{@render install()}{/if}
    {/snippet}
  </Banner>
{:else if kind === 'available' && u?.available}
  <Banner tone="info" icon="download" title={t('update.available', { version: u.available.version })}>
    {#snippet actions()}
      <Button variant="ghost" size="sm" onclick={() => ctl.openUpdate()}>{t('update.notes')}</Button>
      {@render install()}
      <Button variant="ghost" size="icon" label={t('update.dismiss')} title={t('update.dismiss')}
        onclick={() => ctl.dismissUpdate()}><Icon name="x" /></Button>
    {/snippet}
  </Banner>
{:else if kind === 'updated' && u?.updated_to}
  <Banner tone="ok" icon="check" title={t('update.updated', { version: u.updated_to })}>
    {#if u.updated_notes}<span class="whitespace-pre-line">{u.updated_notes}</span>{/if}
    {#snippet actions()}
      <Button variant="ghost" size="icon" label={t('common.close')} title={t('common.close')}
        onclick={() => ctl.dismissUpdated()}><Icon name="x" /></Button>
    {/snippet}
  </Banner>
{/if}
