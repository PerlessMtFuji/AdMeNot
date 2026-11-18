<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import type { FailureView } from '../../lib/types';
  import FailureList from './FailureList.svelte';

  // Nieudane pozycje pod wynikiem: osobna rozwijana lista dla plików, aplikacji i każdego rodzaju telefonii.
  let { failures }: { failures: FailureView[] } = $props();
  const TEL = ['contacts', 'sms', 'mms', 'calls'];
  const groups = $derived.by(() => {
    const out: { key: string; label: string; items: FailureView[] }[] = [];
    const add = (key: string, label: string, f: FailureView) => {
      const g = out.find((x) => x.key === key);
      if (g) g.items.push(f); else out.push({ key, label, items: [f] });
    };
    for (const f of failures) {
      if (f.kind === 'tel') add(`tel:${f.group}`, TEL.includes(f.group) ? t(`transfer.sum.${f.group}`) : f.group, f);
      else add(f.kind, t(f.kind === 'file' ? 'transfer.sum.files' : 'transfer.sum.apps'), f);
    }
    return out;
  });
</script>

{#each groups as g (g.key)}
  <details data-testid="failures-{g.key}" class="rounded-xl border border-line bg-surface px-4 py-2.5">
    <summary class="cursor-pointer text-sm font-semibold text-ink">{t('transfer.fail.title')}: {g.label} ({g.items.length})</summary>
    <div class="mt-2 flex flex-col gap-1"><FailureList failures={g.items} limit={10} /></div>
  </details>
{/each}
