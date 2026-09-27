<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import ConfirmDialog from './ConfirmDialog.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let command = $state('');
  let confirming = $state(false);
  let running = $state(false);
  const enabled = $derived(s.device !== null && s.phase !== 'connect' && !s.orderRunning);

  async function run() {
    const text = command.trim();
    if (!text || !enabled || running) return;
    if (!s.consoleWarned) {
      confirming = true;
      return;
    }
    running = true;
    const result = await ctl.runConsole(text);
    running = false;
    if (result) command = '';
  }

  function accept() {
    s.consoleWarned = true;
    confirming = false;
    void run();
  }
</script>

<section class="flex max-h-[38vh] flex-col border-t-2 border-[#1d2733] bg-[#0f172a] text-[#cbd5e1]"
  aria-label={t('console.title')}>
  <div class="flex items-center gap-2 px-3 py-1.5">
    <b class="text-[12px] text-white">{t('console.title')}</b>
    <button class="ml-auto text-[12px] opacity-80" onclick={() => (s.consoleOpen = false)}>{t('common.close')}</button>
  </div>
  <ol class="mono flex-1 overflow-auto px-3 text-[11px] leading-[1.6]">
    {#each s.console as e, i (i)}
      <li>
        <details>
          <summary class="cursor-pointer">
            <span class="opacity-60">{e.time.slice(11)}</span>
            <span class={e.status === 'ok' ? 'text-[#86efac]' : 'text-[#fca5a5]'}>{e.status}</span>
            {#if e.tag === 'console'}<span class="text-[#fcd34d]">console</span>{/if}
            {e.command}
            <span class="opacity-60">{e.duration.toFixed(2)}s</span>
          </summary>
          <pre class="whitespace-pre-wrap opacity-80">{e.output}</pre>
        </details>
      </li>
    {:else}
      <li class="opacity-60">{t('console.empty')}</li>
    {/each}
  </ol>
  <form class="flex gap-2 px-3 py-2" onsubmit={(e) => { e.preventDefault(); void run(); }}>
    <span class="mono self-center text-[11px] opacity-70">adb shell</span>
    <input class="mono flex-1 rounded bg-[#1e293b] px-2 py-1 text-[12px] text-white" bind:value={command}
      placeholder={t('console.placeholder')} aria-label={t('console.placeholder')} disabled={!enabled} />
    <button class="btn px-2.5 py-1 text-[11px]" disabled={!enabled || running || !command.trim()}>{t('console.run')}</button>
  </form>
  {#if !enabled}<p class="px-3 pb-2 text-[11px] opacity-70">{t('console.disabled')}</p>{/if}
</section>

{#if confirming}
  <ConfirmDialog title={t('console.warn_title')} message={t('console.warn_text')} confirm={t('console.warn_ok')}
    cancel={t('common.cancel')} onconfirm={accept} oncancel={() => (confirming = false)} />
{/if}
