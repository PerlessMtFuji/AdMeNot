<script lang="ts">
  let props: {
    title: string;
    message: string;
    confirm: string;
    cancel: string;
    onconfirm: () => void;
    oncancel: () => void;
  } = $props();
</script>

<div class="modal-backdrop">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
    <b id="confirm-title" class="text-[14px]">{props.title}</b>
    <p class="mt-2">{props.message}</p>
    <div class="mt-4 flex justify-end gap-2">
      <button class="btn" onclick={props.oncancel}>{props.cancel}</button>
      <button class="btn btn-pri" onclick={props.onconfirm}>{props.confirm}</button>
    </div>
  </div>
</div>
