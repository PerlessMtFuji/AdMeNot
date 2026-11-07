<script lang="ts">
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { formatBytes } from '../../lib/explorer/logic';
  import type { ExplorerProblems } from '../../lib/explorer/state.svelte';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import Button from '../../ui/Button.svelte';
  import Dialog from '../../ui/Dialog.svelte';

  /** Plan zadania odrzucony przed startem: konkretny powód każdego problemu, nic nie zostało skopiowane. */
  let { ex, problems }: { ex: ExplorerController; problems: ExplorerProblems } = $props();
  const side = $derived(problems.kind === 'to_pc' ? 'pc' : 'phone');
  const bytes = (v: unknown) => formatBytes(Number(v) || 0, i18n.lang);
  const names = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
  const base = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() ?? p;
  const pickable = $derived(problems.kind === 'to_pc' && problems.list.some((p) => p.key !== 'denied'));

  async function change(): Promise<void> {
    ex.dismissProblems();
    await ex.pickDest();
  }
</script>

<Dialog title={t(`explorer.problems.title_${side}`)} oncancel={() => ex.dismissProblems()}>
  <p class="mb-3">{t('explorer.problems.intro')}</p>
  <ul class="flex flex-col gap-3 text-sm text-ink">
    {#each problems.list as p (p.key)}
      <li>
        {#if p.key === 'no_space'}
          {t(`explorer.problems.no_space_${side}`, { missing: bytes(p.detail.missing), need: bytes(p.detail.need), free: bytes(p.detail.free) })}
        {:else if p.key === 'read_only'}
          {t('explorer.problems.read_only', { path: String(p.detail.path ?? '') })}
        {:else if p.key === 'path_too_long'}
          {tp(`explorer.problems.path_too_long_${side}`, Number(p.detail.count) || 0, { limit: Number(p.detail.limit) || 0 })}
        {:else if p.key === 'fat32_big'}
          {t('explorer.problems.fat32')}
          <ul class="mt-1.5 ml-4 list-disc text-mut">
            {#each names(p.detail.names) as n, i (i)}<li class="break-all">{n}</li>{/each}
          </ul>
          <Button size="sm" class="mt-2" onclick={() => ex.copyWithout(names(p.detail.paths))}>{t('explorer.problems.skip')}</Button>
        {:else}
          {t(`explorer.problems.denied_${side}`)}
          <ul class="mt-1.5 ml-4 list-disc text-mut">
            {#each names(p.detail.paths).map(base) as n, i (i)}<li class="break-all">{n}</li>{/each}
          </ul>
          {#if problems.kind === 'to_pc'}
            <Button size="sm" class="mt-2" onclick={() => ex.copyWithout(names(p.detail.paths))}>{t('explorer.problems.skip')}</Button>
          {/if}
        {/if}
      </li>
    {/each}
  </ul>
  {#snippet actions()}
    {#if pickable}<Button onclick={change}>{t('explorer.problems.change_dest')}</Button>{/if}
    <Button variant="primary" onclick={() => ex.dismissProblems()}>{t('common.close')}</Button>
  {/snippet}
</Dialog>
