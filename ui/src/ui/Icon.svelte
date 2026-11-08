<script lang="ts" module>
  import ArrowLeft from '@lucide/svelte/icons/arrow-left';
  import BellRing from '@lucide/svelte/icons/bell-ring';
  import Camera from '@lucide/svelte/icons/camera';
  import Check from '@lucide/svelte/icons/check';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import Clock from '@lucide/svelte/icons/clock';
  import Copy from '@lucide/svelte/icons/copy';
  import Download from '@lucide/svelte/icons/download';
  import Eye from '@lucide/svelte/icons/eye';
  import FileText from '@lucide/svelte/icons/file-text';
  import Heart from '@lucide/svelte/icons/heart';
  import HistoryIcon from '@lucide/svelte/icons/history';
  import Info from '@lucide/svelte/icons/info';
  import Lock from '@lucide/svelte/icons/lock';
  import LockOpen from '@lucide/svelte/icons/lock-open';
  import Megaphone from '@lucide/svelte/icons/megaphone';
  import Pause from '@lucide/svelte/icons/pause';
  import Plus from '@lucide/svelte/icons/plus';
  import QrCode from '@lucide/svelte/icons/qr-code';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import ScanSearch from '@lucide/svelte/icons/scan-search';
  import ScreenShare from '@lucide/svelte/icons/screen-share';
  import ScreenShareOff from '@lucide/svelte/icons/screen-share-off';
  import Search from '@lucide/svelte/icons/search';
  import SettingsIcon from '@lucide/svelte/icons/settings';
  import ShieldAlert from '@lucide/svelte/icons/shield-alert';
  import ShieldUser from '@lucide/svelte/icons/shield-user';
  import ShieldX from '@lucide/svelte/icons/shield-x';
  import Smartphone from '@lucide/svelte/icons/smartphone';
  import Terminal from '@lucide/svelte/icons/terminal';
  import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import Undo2 from '@lucide/svelte/icons/undo-2';
  import VenetianMask from '@lucide/svelte/icons/venetian-mask';
  import X from '@lucide/svelte/icons/x';
  import Zap from '@lucide/svelte/icons/zap';
  import ArrowDown from '@lucide/svelte/icons/arrow-down';
  import ArrowUp from '@lucide/svelte/icons/arrow-up';
  import FileIcon from '@lucide/svelte/icons/file';
  import Film from '@lucide/svelte/icons/film';
  import Folder from '@lucide/svelte/icons/folder';
  import FolderLock from '@lucide/svelte/icons/folder-lock';
  import FolderOpen from '@lucide/svelte/icons/folder-open';
  import HardDrive from '@lucide/svelte/icons/hard-drive';
  import ImageIcon from '@lucide/svelte/icons/image';
  import LayoutGrid from '@lucide/svelte/icons/layout-grid';
  import List from '@lucide/svelte/icons/list';
  import MessageCircle from '@lucide/svelte/icons/message-circle';
  import Music from '@lucide/svelte/icons/music';
  import MapPin from '@lucide/svelte/icons/map-pin';
  import Package from '@lucide/svelte/icons/package';
  import Play from '@lucide/svelte/icons/play';
  import RotateCw from '@lucide/svelte/icons/rotate-cw';
  import SkipForward from '@lucide/svelte/icons/skip-forward';
  import ScanLine from '@lucide/svelte/icons/scan-line';
  import Upload from '@lucide/svelte/icons/upload';
  import WifiOff from '@lucide/svelte/icons/wifi-off';
  import ArrowLeftRight from '@lucide/svelte/icons/arrow-left-right';
  import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
  import Wrench from '@lucide/svelte/icons/wrench';
  import Ellipsis from '@lucide/svelte/icons/ellipsis';
  import StickyNote from '@lucide/svelte/icons/sticky-note';

  export const ICONS = {
    ellipsis: Ellipsis, 'sticky-note': StickyNote,
    megaphone: Megaphone, 'bell-ring': BellRing, lock: Lock, 'lock-open': LockOpen, eye: Eye,
    'venetian-mask': VenetianMask, clock: Clock, download: Download, zap: Zap, check: Check, x: X,
    'triangle-alert': TriangleAlert, info: Info, 'undo-2': Undo2, 'trash-2': Trash2, 'rotate-ccw': RotateCcw, 'arrow-left': ArrowLeft,
    'chevron-down': ChevronDown, 'chevron-right': ChevronRight, search: Search, terminal: Terminal,
    history: HistoryIcon, settings: SettingsIcon, plus: Plus, pause: Pause, 'qr-code': QrCode, smartphone: Smartphone,
    'shield-x': ShieldX, 'shield-alert': ShieldAlert, 'shield-user': ShieldUser, 'scan-search': ScanSearch,
    'file-text': FileText, camera: Camera, 'screen-share': ScreenShare, 'screen-share-off': ScreenShareOff,
    heart: Heart, copy: Copy, 'arrow-down': ArrowDown, 'arrow-up': ArrowUp, file: FileIcon, film: Film, folder: Folder,
    'folder-lock': FolderLock, 'folder-open': FolderOpen, 'hard-drive': HardDrive, image: ImageIcon,
    'layout-grid': LayoutGrid, list: List, 'message-circle': MessageCircle, music: Music, package: Package, play: Play,
    'scan-line': ScanLine, 'chevron-left': ChevronLeft, 'map-pin': MapPin, 'rotate-cw': RotateCw, 'skip-forward': SkipForward, upload: Upload, 'wifi-off': WifiOff,
    'arrow-left-right': ArrowLeftRight, 'sliders-horizontal': SlidersHorizontal, wrench: Wrench,
  } as const;
  export type IconName = keyof typeof ICONS;
</script>

<script lang="ts">
  let { name, size = 16, strokeWidth = 2, class: cls = '' }:
    { name: IconName; size?: number; strokeWidth?: number; class?: string } = $props();
  const Glyph = $derived(ICONS[name]);
</script>

<Glyph {size} {strokeWidth} class="flex-none {cls}" aria-hidden="true" />
