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
  class="flex flex-none flex-col bg-[#0b1020] text-[#cbd5e1] shadow-[0_-12px_30px_-18px_rgb(79_70_229/.6)]" transition:fly={{ y: 40, duration: ms(DUR.enter) }}>
  <button type="button" aria-label={t('console.resize')} onpointerdown={resize}
    class="grid h-3 w-full flex-none cursor-ns-resize place-items-center border-t border-[#312e81]/60 bg-[#111733] after:h-1 after:w-10 after:rounded-full after:bg-[#4f46e5]/50 hover:after:bg-[#818cf8]"></button>
  <div class="flex items-center gap-2 px-4 py-2">
    <Icon name="terminal" /><b class="text-sm text-white">{t('console.title')}</b>
    <button class="ml-auto text-sm opacity-80 hover:opacity-100" onclick={() => (s.consoleOpen = false)}>{t('common.close')}</button>
  </div>
  <ol class="scroll-fade mono min-h-0 flex-1 overflow-auto px-4 text-xs leading-[1.7]">
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
    <span class="mono self-center text-xs opacity-70">adb shell</span>
    <input class="mono flex-1 rounded-[10px] bg-[#151c35] px-3 py-2 text-sm text-white ring-1 ring-[#312e81] outline-none focus:ring-[#818cf8] focus:shadow-[0_0_0_4px_rgb(129_140_248/.2)]" bind:value={command}
      placeholder={t('console.placeholder')} aria-label={t('console.placeholder')} disabled={!enabled} />
    <Button type="submit" size="sm" variant="primary" disabled={!enabled || running || !command.trim()}>{t('console.run')}</Button>
  </form>
  {#if !enabled}<p class="px-4 pb-2 text-xs opacity-70">{t('console.disabled')}</p>{/if}
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
