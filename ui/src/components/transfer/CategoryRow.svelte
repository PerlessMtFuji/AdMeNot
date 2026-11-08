<script lang="ts">
  import type { Component, Snippet } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';

  // Jeden wiersz = jedna kategoria: [pole wyboru] ikona, nazwa + liczba, linia pod spodem, etykiety,
  // „Pokaż ▾” (zwinięte szczegóły), rozmiar albo wynik po prawej. Problem to etykieta w wierszu, a opis
  // „jak …?” siedzi w zwinięciu i otwiera się dopiero po kliknięciu.
  let { icon: Glyph, name, count, size, sub, checked, disabled = false, ontoggle, tone = null, pills, fold, foldLabel, foldText,
    foldOpen, onfold, result }: {
    icon: Component<{ size?: number; strokeWidth?: number; 'aria-hidden'?: 'true' }>;
    name: string;
    count?: string;
    size?: string;
    sub?: string;
    checked?: boolean;
    disabled?: boolean;
    ontoggle?: () => void;
    tone?: 'warn' | 'block' | null;
    pills?: Snippet;
    fold?: Snippet;
    foldLabel?: string;
    /** Własny podpis przycisku zamiast „Pokaż”, np. „jak skopiować?” (strzałka ▾/▴ dochodzi sama). */
    foldText?: string;
    /** Tryb sterowany: stan trzyma rodzic (`onfold`). Bez niego wiersz sam pamięta, zwinięty na starcie. */
    foldOpen?: boolean;
    onfold?: (open: boolean) => void;
    result?: { text: string; tone: 'ok' | 'warn' };
  } = $props();

  const uid = $props.id();
  let ownOpen = $state(false);
  const open = $derived(foldOpen ?? ownOpen);
  const toggleText = $derived(foldText ? `${foldText} ${open ? '▴' : '▾'}` : open ? t('transfer.row.hide') : t('transfer.row.show'));
  const foldId = `fold-${uid}`;
  const hasBox = $derived(ontoggle !== undefined || checked !== undefined);
  const TINT = { warn: 'bg-warn-soft/50', block: 'bg-gradient-to-r from-warn-soft to-transparent to-70%' };

  function toggleFold() {
    const next = !open;
    ownOpen = next;
    onfold?.(next);
  }
</script>

<div data-tone={tone}>
  <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5 {tone ? TINT[tone] : ''}">
    <div class="flex min-w-[15rem] flex-1 items-center gap-3">
    {#if hasBox}
      <input type="checkbox" class="h-[17px] w-[17px] flex-none accent-accent" checked={checked ?? false} {disabled}
        aria-label={name} onchange={() => ontoggle?.()} />
    {/if}
    <span class="grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] bg-accent-soft text-accent" aria-hidden="true">
      <Glyph size={16} strokeWidth={2} aria-hidden="true" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="font-bold [overflow-wrap:anywhere] text-ink">{name}</span>{#if count}<span class="ml-1 font-semibold text-soft">{count}</span>{/if}
      {#if sub}<span class="block text-[12.5px] leading-snug text-mut">{sub}</span>{/if}
    </span>
    </div>
    {#if pills || fold || size || result}
    <div class="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-1.5">
    {#if pills}<span class="flex flex-none flex-wrap items-center justify-end gap-1.5">{@render pills()}</span>{/if}
    {#if fold}
      <button type="button" class="flex-none cursor-pointer text-[13px] font-semibold whitespace-nowrap text-accent hover:underline"
        aria-expanded={open} aria-controls={foldId} aria-label={foldLabel ? `${foldLabel}: ${toggleText}` : undefined}
        onclick={toggleFold}>{toggleText}</button>
    {/if}
    {#if size}<span class="mono flex-none text-[12.5px] whitespace-nowrap text-mut">{size}</span>{/if}
    {#if result}
      <span class="flex-none font-bold whitespace-nowrap tabular-nums {result.tone === 'ok' ? 'text-ok' : 'text-warn'}">{result.text}</span>
    {/if}
    </div>
    {/if}
  </div>
  {#if fold}
    <div id={foldId} hidden={!open} class="pr-4 pt-1 pb-3 text-[13px] {hasBox ? 'pl-[75px]' : 'pl-[58px]'} text-mut">
      {#if open}{@render fold()}{/if}
    </div>
  {/if}
</div>
