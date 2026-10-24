<script lang="ts" module>
  import brave from '../assets/browsers/brave.webp';
  import chrome from '../assets/browsers/chrome.webp';
  import edge from '../assets/browsers/edge.webp';
  import firefox from '../assets/browsers/firefox.webp';
  import opera from '../assets/browsers/opera.webp';
  import samsung from '../assets/browsers/samsung.webp';
  import vivaldi from '../assets/browsers/vivaldi.webp';
  import yandex from '../assets/browsers/yandex.webp';

  // Przeglądarek zwykle nie analizujemy (Chrome jest systemowy), więc ich ikony z APK nie ma: dla popularnych
  // pakietów ikona wbudowana (źródła i licencje: assets/browsers/SOURCES.md), dla reszty inicjał.
  const BUILT_IN: Record<string, string> = {
    'com.android.chrome': chrome, 'com.chrome.beta': chrome, 'com.chrome.dev': chrome, 'com.chrome.canary': chrome,
    'com.sec.android.app.sbrowser': samsung, 'com.sec.android.app.sbrowser.beta': samsung,
    'org.mozilla.firefox': firefox, 'org.mozilla.firefox_beta': firefox, 'org.mozilla.fenix': firefox,
    'com.microsoft.emmx': edge, 'com.microsoft.emmx.beta': edge,
    'com.opera.browser': opera, 'com.opera.browser.beta': opera, 'com.opera.mini.native': opera,
    'com.brave.browser': brave, 'com.brave.browser_beta': brave,
    'com.vivaldi.browser': vivaldi, 'com.vivaldi.browser.snapshot': vivaldi,
    'com.yandex.browser': yandex, 'com.yandex.browser.lite': yandex,
  };

  /** Wbudowane logo popularnej przeglądarki (undefined dla innych pakietów) — dla ekranów z własnym wyglądem ikony. */
  export function builtInIcon(pkg: string): string | undefined {
    return Object.hasOwn(BUILT_IN, pkg) ? BUILT_IN[pkg] : undefined;
  }
</script>

<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { initial } from '../lib/logic';
  import AppIcon from './AppIcon.svelte';

  // md: nagłówek wiersza, sm: podpis przy witrynie.
  let { pkg, name, size = 'md' }: { pkg: string; name: string; size?: 'md' | 'sm' } = $props();
  const box = $derived(size === 'md' ? 'h-7 w-7 text-sm' : 'h-4 w-4 text-[9px]');
  const ctl = getContext<Controller>('ctl');
  // Prawdziwa ikona z telefonu (gdy przeglądarkę analizowano) ma pierwszeństwo przed wbudowaną.
  const icon = $derived(ctl.state.scan?.apps.find((a) => a.package === pkg)?.icon ?? BUILT_IN[pkg]);
</script>

<AppIcon {icon} class={box}>
  <span class="grid flex-none place-items-center rounded-[28%] bg-neutral-soft font-extrabold text-mut {box}"
    aria-hidden="true">{initial(name)}</span>
</AppIcon>
