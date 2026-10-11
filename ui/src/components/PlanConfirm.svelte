<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { initial, planGroups, type PlanGroupKey } from '../lib/logic';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import AppIcon from './AppIcon.svelte';
  import ShareQr from './ShareQr.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
  // Grupy wg akcji, jak strona planu dla klienta: wspólne kroki raz pod nagłówkiem, przy aplikacji tylko reszta.
  const groups = $derived(s.plan ? planGroups(s.plan.apps, s.settings.lang) : []);
  const icons = $derived(new Map((s.scan?.apps ?? []).map((a) => [a.package, a.icon])));
  const DOT: Record<PlanGroupKey, string> = { remove: 'bg-bad', disable: 'bg-warn', silence: 'bg-accent', blocked: 'bg-soft' };
  // Odblokowanie pakietu chronionego to świadoma decyzja: trzeba przepisać jego nazwę
  // (audyt 2026-10-11, QA-01), jak `--unlock PAKIET` w CLI.
  let confirming = $state<string | null>(null);
  let typed = $state('');
  function startUnlock(pkg: string): void {
    confirming = pkg;
    typed = '';
  }
  async function confirmUnlock(pkg: string): Promise<void> {
    if (typed.trim() !== pkg) return;
    confirming = null;
    await ctl.unlock(pkg);
  }
</script>

{#if s.plan}
  {@const plan = s.plan}
  <section aria-label={t('plan.title')} class="flex min-h-0 flex-1 flex-col gap-3">
    <h2 class="text-lg font-bold">{t('plan.confirm_title')}</h2>
    <div class="scroll-fade -mr-2 flex min-h-0 flex-col gap-2.5 overflow-auto pr-2">
      {#each groups as g (g.key)}
        {@const title = `${t(`plan.groups.${g.key}`)} (${g.apps.length})`}
        <div class="well flex-none p-3.5 {g.key === 'blocked' ? 'opacity-60' : ''}">
          <h3 class="flex items-center gap-2 font-bold"><span class="h-2.5 w-2.5 flex-none rounded-full {DOT[g.key]}"></span>{title}</h3>
          <ul aria-label={title} class="mt-2 flex flex-col gap-1.5">
            {#each g.apps as a (a.package)}
              <li>
                <div class="flex items-center gap-2.5">
                  <AppIcon icon={icons.get(a.package)} class="h-7 w-7"><span class="grid h-7 w-7 flex-none place-items-center rounded-[9px] bg-neutral-soft text-sm font-extrabold text-mut" aria-hidden="true">{initial(a.name)}</span></AppIcon>
                  <b class="min-w-0 flex-1 truncate">{a.name}</b>
                </div>
                {#if a.blocked}
                  <p class="mt-1 text-sm text-bad">{a.reason_text}</p>
                  {#if a.reason === 'protected' && expert}
                    {#if confirming === a.package}
                      <p class="mt-1.5 text-sm text-warn">{t('plan.unlock_prompt', { package: a.package })}</p>
                      <div class="mt-1.5 flex gap-2">
                        <input class="field mono min-w-0 flex-1 rounded-[10px] px-2.5 py-1.5 text-sm" bind:value={typed}
                          aria-label={t('plan.unlock_label')} placeholder={a.package} autocomplete="off" spellcheck="false" />
                        <Button variant="danger" size="sm" disabled={typed.trim() !== a.package}
                          onclick={() => confirmUnlock(a.package)}>{t('plan.unlock')}</Button>
                        <Button variant="ghost" size="sm" onclick={() => (confirming = null)}>{t('common.cancel')}</Button>
                      </div>
                    {:else}
                      <Button variant="ghost" size="sm" class="mt-1" onclick={() => startUnlock(a.package)}>
                        <Icon name="lock-open" />{t('plan.unlock')}
                      </Button>
                    {/if}
                  {/if}
                {/if}
              </li>
            {/each}
          </ul>
          {#if g.steps.length}
            <!-- kroki całej grupy w kolejności wykonania; krok nie dla wszystkich ma dopisek z nazwami -->
            <ul aria-label="{t('plan.steps')}: {title}" class="mt-2.5 flex flex-col gap-0.5 border-t border-line pt-2 text-sm text-mut">
              {#each g.steps as step (step.text)}
                <li class="flex gap-2"><span class="mt-[7px] h-1 w-1 flex-none rounded-full bg-soft"></span>
                  <span>{step.text}{#if step.only.length}<span class="text-soft">{` — ${t('plan.only', { names: step.only.join(', ') })}`}</span>{/if}</span></li>
              {/each}
            </ul>
          {/if}
          {#each g.warnings as w (w.text)}
            <p class="mt-1.5 rounded-lg bg-warn-soft px-2 py-1 text-sm text-warn">{w.only.length ? `${w.only.join(', ')}: ` : ''}{w.text}</p>
          {/each}
        </div>
      {/each}
    </div>
    {#if plan.runnable === 0}<p class="text-bad">{t('plan.nothing')}</p>{/if}
    <ShareQr disabled={plan.runnable === 0 || s.orderRunning} />
    <div class="mt-auto text-xs text-mut">{t('plan.undo_hint')}</div>
    <div class="flex gap-2">
      <Button variant="ghost" onclick={() => ctl.closePlan()}>{t('common.back')}</Button>
      <Button variant="primary" size="lg" class="flex-1" disabled={plan.runnable === 0 || s.orderRunning}
        onclick={() => ctl.execute()}>{t('plan.run', { count: plan.runnable })}</Button>
    </div>
  </section>
{/if}
