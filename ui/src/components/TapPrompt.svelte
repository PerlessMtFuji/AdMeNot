<script lang="ts" module>
  import { t } from '../lib/i18n/index.svelte';
  import { smsAppKey } from '../lib/logic';

  /** Poprzednia domyślna aplikacja SMS: znana etykieta, inaczej pakiet, a bez pakietu — ogólna nazwa. */
  export function smsAppName(pkg: string | null): string {
    const key = smsAppKey(pkg);
    return key ? t(`transfer.restore.sms_app.${key}`) : pkg ?? t('transfer.restore.sms_app.previous');
  }
</script>

<script lang="ts">
  // Prośba o stuknięcie na telefonie (`transfer:tap`) — w czasie wgrywania i przy przywracaniu ustawień
  // telefonu po przerwanym wgrywaniu. Oddania roli SMS poprzedniej aplikacji nie da się pominąć.
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';

  const ctl = getContext<Controller>('ctl');
  const r = $derived(ctl.state.transfer.restore);
</script>

{#if r.tap === 'sms_role_grant'}
  <Banner tone="warn" icon="smartphone" title={t('transfer.restore.tap.grant')}>
    {t('transfer.restore.tap.grant_text')}
    {#snippet actions()}
      <Button size="sm" onclick={() => ctl.skipTap()}>{t('transfer.restore.tap.skip')}</Button>
    {/snippet}
  </Banner>
{:else if r.tap === 'sms_role_restore'}
  <Banner tone="bad" icon="smartphone" title={t('transfer.restore.tap.restore', { app: smsAppName(r.tapPackage) })}>
    {t('transfer.restore.tap.restore_text')}
  </Banner>
{/if}
