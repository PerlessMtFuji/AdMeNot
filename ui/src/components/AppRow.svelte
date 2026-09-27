<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { levelTag, verdictColor } from '../lib/logic';
  import type { AppView } from '../lib/types';

  let props: { app: AppView } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const level = $derived(s.selection[props.app.package] ?? null);
  const shown = $derived(level ?? props.app.default_level);
</script>

<div class="card flex items-start gap-2.5 {s.apk.changed.includes(props.app.package) ? 'flash' : ''} {level ? '' : 'opacity-80'}">
  <input type="checkbox" class="mt-0.5 h-3.5 w-3.5 accent-[#1d2733]" checked={level !== null}
    aria-label={props.app.name} onchange={() => ctl.toggle(props.app)} />
  <span class="h-7 w-7 flex-none rounded-lg" style="background: {verdictColor(props.app.verdict)}" aria-hidden="true"></span>
  <div class="min-w-0 flex-1">
    <b class="text-[12.5px]">{props.app.name}</b>
    <p class="mt-0.5 text-[11.5px] text-[#475569]">{props.app.problems.join(' ')}</p>
  </div>
  <span class="tag {levelTag(shown)}">{t(`level.${shown ?? 'review'}`)}</span>
</div>
