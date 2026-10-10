<script lang="ts">
  import { getContext } from 'svelte';
  import logo from '../assets/admenot.svg';
  import ErrorCard from '../components/ErrorCard.svelte';
  import PrivacyChoices from '../components/PrivacyChoices.svelte';
  import RiskWarning from '../components/RiskWarning.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { Lang } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Segmented from '../ui/Segmented.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  // Ponowne pokazanie (nowa wersja ostrzeżenia): przełączniki startują od obecnych zgód.
  let telemetry = $state(s.settings.telemetry);
  let packages = $state(s.settings.telemetry_packages);
  let accepted = $state(false);
  let busy = $state(false);
  const langs: { value: Lang; label: string }[] = [{ value: 'pl', label: 'Polski' }, { value: 'en', label: 'English' }];

  async function start(): Promise<void> {
    busy = true;  // podwójny klik nie wysyła drugiej akceptacji
    await ctl.acceptWelcome(telemetry, packages && telemetry);
    busy = false;
  }
</script>

<main class="flex h-full justify-center overflow-y-auto p-6">
  <div class="flex w-full max-w-2xl flex-col gap-5">
    <div class="flex items-center gap-3">
      <img src={logo} alt="" aria-hidden="true" class="h-10 w-10" />
      <h1 class="flex-1 text-2xl font-extrabold">{t('welcome.title')}</h1>
      <Segmented label={t('settings.lang')} value={s.settings.lang} options={langs} onchange={(v) => ctl.setLang(v)} />
    </div>
    <p class="text-mut">{t('welcome.lead')}</p>
    <RiskWarning />
    <label class="flex items-center gap-3 font-semibold">
      <input type="checkbox" bind:checked={accepted} />
      <span>{t('welcome.accept')}</span>
    </label>
    <Card><div class="flex flex-col gap-3 p-6">
      <span class="lbl">{t('privacy.title')}</span>
      <PrivacyChoices {telemetry} {packages} onchange={(tel, pkg) => { telemetry = tel; packages = pkg; }} />
      <span class="text-xs text-mut">{t('welcome.later')}</span>
    </div></Card>
    {#if s.error}<ErrorCard />{/if}  <!-- np. ustawienia z nowszej wersji: ekran zostaje, nic nie zapisane -->
    <div><Button variant="primary" disabled={!accepted || busy} onclick={start}>{t('welcome.start')}</Button></div>
  </div>
</main>
