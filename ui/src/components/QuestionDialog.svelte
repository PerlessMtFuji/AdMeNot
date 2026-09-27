<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
</script>

{#if s.question}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="question-title">
      <b id="question-title" class="text-[14px]">{t('question.admin.title')}</b>
      <p class="mt-2">{t('question.admin.text', { name: s.question.name })}</p>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn" onclick={() => ctl.answer('skip')}>{t('question.admin.skip')}</button>
        <button class="btn btn-pri" onclick={() => ctl.answer('retry')}>{t('question.admin.retry')}</button>
      </div>
    </div>
  </div>
{/if}
