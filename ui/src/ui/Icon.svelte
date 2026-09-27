<script lang="ts" module>
  import BellRing from '@lucide/svelte/icons/bell-ring';
  import Check from '@lucide/svelte/icons/check';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import Clock from '@lucide/svelte/icons/clock';
  import Download from '@lucide/svelte/icons/download';
  import Eye from '@lucide/svelte/icons/eye';
  import HistoryIcon from '@lucide/svelte/icons/history';
  import Info from '@lucide/svelte/icons/info';
  import Lock from '@lucide/svelte/icons/lock';
  import LockOpen from '@lucide/svelte/icons/lock-open';
  import Megaphone from '@lucide/svelte/icons/megaphone';
  import Pause from '@lucide/svelte/icons/pause';
  import Plus from '@lucide/svelte/icons/plus';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import ScanSearch from '@lucide/svelte/icons/scan-search';
  import Search from '@lucide/svelte/icons/search';
  import SettingsIcon from '@lucide/svelte/icons/settings';
  import ShieldAlert from '@lucide/svelte/icons/shield-alert';
  import ShieldUser from '@lucide/svelte/icons/shield-user';
  import ShieldX from '@lucide/svelte/icons/shield-x';
  import Smartphone from '@lucide/svelte/icons/smartphone';
  import Terminal from '@lucide/svelte/icons/terminal';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
  import Undo2 from '@lucide/svelte/icons/undo-2';
  import VenetianMask from '@lucide/svelte/icons/venetian-mask';
  import X from '@lucide/svelte/icons/x';
  import Zap from '@lucide/svelte/icons/zap';

  export const ICONS = {
    megaphone: Megaphone, 'bell-ring': BellRing, lock: Lock, 'lock-open': LockOpen, eye: Eye,
    'venetian-mask': VenetianMask, clock: Clock, download: Download, zap: Zap, check: Check, x: X,
    'triangle-alert': TriangleAlert, info: Info, 'undo-2': Undo2, 'rotate-ccw': RotateCcw,
    'chevron-down': ChevronDown, 'chevron-right': ChevronRight, search: Search, terminal: Terminal,
    history: HistoryIcon, settings: SettingsIcon, plus: Plus, pause: Pause, smartphone: Smartphone,
    'shield-x': ShieldX, 'shield-alert': ShieldAlert, 'shield-user': ShieldUser, 'scan-search': ScanSearch,
  } as const;
  export type IconName = keyof typeof ICONS;
</script>

<script lang="ts">
  let { name, size = 16, strokeWidth = 2, class: cls = '' }:
    { name: IconName; size?: number; strokeWidth?: number; class?: string } = $props();
  const Glyph = $derived(ICONS[name]);
</script>

<Glyph {size} {strokeWidth} class="flex-none {cls}" aria-hidden="true" />
