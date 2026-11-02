<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import Icon from '../ui/Icon.svelte';

  // Kopiowanie IMEI do schowka (np. do zlecenia w systemie serwisu). Bywa w <label> wiersza listy
  // telefonów: klik nie może zmieniać wyboru telefonu, więc zatrzymujemy domyślną akcję etykiety.
  let { imei }: { imei: string } = $props();
  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  function copy(e: MouseEvent): void {
    e.preventDefault();
    e.stopPropagation();
    navigator.clipboard?.writeText(imei).then(() => {
      copied = true;
      clearTimeout(timer);
      timer = setTimeout(() => (copied = false), 1500);
    }).catch(() => {});
  }
</script>

<button type="button" class="inline-grid h-5 w-5 flex-none place-items-center rounded text-soft hover:bg-neutral-soft hover:text-accent
  {copied ? '!text-ok' : ''}" title={t('phone.copy_imei')} aria-label={t('phone.copy_imei')} onclick={copy}>
  <Icon name={copied ? 'check' : 'copy'} size={12} />
</button>
<span class="sr-only" role="status">{copied ? t('phone.imei_copied') : ''}</span>
