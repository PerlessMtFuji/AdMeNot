<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';

  type Info = { name: string; address: string; phone: string; email: string; nip: string; website: string;
    logo: string | null; technician: string; footer: string };
  let { info }: { info: Info } = $props();

  // Przybliżenie nagłówka i stopki protokołu — tekst użytkownika zawsze jako tekst (nigdy {@html}).
  const name = $derived(info.name.trim());
  const contact = $derived([info.phone, info.email, info.website, info.nip ? t('settings.preview_nip', { nip: info.nip.trim() }) : '']
    .map((x) => x.trim()).filter(Boolean));
  const footer = $derived(info.footer.trim());
  const technician = $derived(info.technician.trim());
</script>

<div data-protocol-preview class="card rounded-[14px] p-4">
  <h3 class="mb-2.5 text-xs font-extrabold tracking-wide text-soft uppercase">{t('settings.preview_title')}</h3>
  <div class="rounded-[10px] border border-line bg-surface-2 p-3.5 text-xs">
    <div class="flex items-start gap-3 border-b border-line pb-2.5">
      {#if info.logo}
        <span class="grid h-10 w-10 flex-none place-items-center rounded-lg border border-line bg-surface text-soft"
          title={info.logo}><Icon name="image" size={18} /></span>
      {/if}
      <div class="min-w-0 flex-1">
        {#if name}
          <b class="block text-sm">{name}</b>
        {:else}
          <b class="block text-sm text-warn">{t('settings.service_name_missing')}</b>
        {/if}
        {#if info.address.trim()}<span class="block whitespace-pre-line text-mut">{info.address.trim()}</span>{/if}
        {#if contact.length}<span class="block text-mut">{contact.join(' · ')}</span>{/if}
      </div>
    </div>
    <p class="py-3 text-soft">{t('settings.preview_body')}</p>
    <div class="flex justify-end">
      <div class="min-w-[160px] text-center">
        {#if technician}<span class="block text-ink">{technician}</span>{/if}
        <span class="block border-t border-line pt-0.5 text-soft">{t('settings.preview_signature')}</span>
      </div>
    </div>
    {#if footer}
      <p class="mt-3 border-t border-line pt-2.5 whitespace-pre-line text-mut">{footer}</p>
    {/if}
  </div>
  <p class="mt-2 text-xs text-soft">{t('settings.preview_note')}</p>
</div>
