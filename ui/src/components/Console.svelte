<script lang="ts">
  import { getContext } from 'svelte';
  import { fly } from 'svelte/transition';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { DUR, ms } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let command = $state('');
  let confirming = $state(false);
  let running = $state(false);
  let height = $state(280);
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

  function resize(e: PointerEvent) {
    const startY = e.clientY;
    const start = height;
    const move = (ev: PointerEvent) => {
      height = Math.min(window.innerHeight * 0.8, Math.max(140, start + startY - ev.clientY));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }
</script>

<section aria-label={t('console.title')} style="height: {height}px"
  class="flex flex-none flex-col bg-[#0f172a] text-[#cbd5e1]" transition:fly={{ y: 40, duration: ms(DUR.enter) }}>
  <button type="button" aria-label={t('console.resize')} onpointerdown={resize}
    class="h-2 w-full flex-none cursor-ns-resize bg-[#1e293b] hover:bg-[#334155]"></button>
  <div class="flex items-center gap-2 px-4 py-2">
    <Icon name="terminal" /><b class="text-[12px] text-white">{t('console.title')}</b>
    <button class="ml-auto text-[12px] opacity-80 hover:opacity-100" onclick={() => (s.consoleOpen = false)}>{t('common.close')}</button>
  </div>
  <ol class="mono min-h-0 flex-1 overflow-auto px-4 text-[11px] leading-[1.6]">
    {#each s.console as e, i (i)}
      <li>
        <details>
          <summary class="flex cursor-pointer items-center gap-2">
            <span class="h-1.5 w-1.5 flex-none rounded-full {e.status === 'ok' ? 'bg-[#4ade80]' : 'bg-[#f87171]'}" aria-hidden="true"></span>
            <span class="opacity-60">{e.time.slice(11)}</span>
            {#if e.tag === 'console'}<span class="text-[#fcd34d]">console</span>{/if}
            <span class="truncate">{e.command}</span>
            <span class="ml-auto opacity-60">{e.status} · {e.duration.toFixed(2)}s</span>
          </summary>
          <pre class="pl-4 whitespace-pre-wrap opacity-80">{e.output}</pre>
        </details>
      </li>
    {:else}
      <li class="opacity-60">{t('console.empty')}</li>
    {/each}
  </ol>
  <form class="flex gap-2 px-4 py-2.5" onsubmit={(e) => { e.preventDefault(); void run(); }}>
    <span class="mono self-center text-[11px] opacity-70">adb shell</span>
    <input class="mono flex-1 rounded-lg bg-[#1e293b] px-2.5 py-1.5 text-[12px] text-white" bind:value={command}
      placeholder={t('console.placeholder')} aria-label={t('console.placeholder')} disabled={!enabled} />
    <Button type="submit" size="sm" variant="primary" disabled={!enabled || running || !command.trim()}>{t('console.run')}</Button>
  </form>
  {#if !enabled}<p class="px-4 pb-2 text-[11px] opacity-70">{t('console.disabled')}</p>{/if}
</section>

{#if confirming}
  <Dialog title={t('console.warn_title')} oncancel={() => (confirming = false)}>
    {t('console.warn_text')}
    {#snippet actions()}
      <Button onclick={() => (confirming = false)}>{t('common.cancel')}</Button>
      <Button variant="primary" onclick={accept}>{t('console.warn_ok')}</Button>
    {/snippet}
  </Dialog>
{/if}
