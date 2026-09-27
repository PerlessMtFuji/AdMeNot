<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';

  let { state }: { state: 'wait' | 'auth' | 'offline' | 'ok' } = $props();
  const time = new Date().toTimeString().slice(0, 5);
  const CORD = 'M125 268 C125 296 112 306 86 308 S 20 310 -20 312';
</script>

<div class="stage" data-state={state} aria-hidden="true">
  <div class="ring"></div>
  <div class="phone">
    <div class="port"></div>
    <div class="screen">
      <div class="view lock" class:shown={state === 'wait' || state === 'offline'}><b>{time}</b></div>
      <div class="view" class:shown={state === 'auth'}>
        <div class="dlg"><b>{t('connect.phone_dialog')}</b><div class="allow">{t('connect.phone_allow')}</div></div>
      </div>
      <div class="view ok" class:shown={state === 'ok'}><div class="check">✓</div></div>
    </div>
  </div>
  <svg class="cable" viewBox="0 0 250 350">
    <defs>
      <linearGradient id="ps-boot" x1="0" x2="1"><stop offset="0" stop-color="#1f2937" /><stop offset=".45" stop-color="#4b5563" /><stop offset="1" stop-color="#111827" /></linearGradient>
      <linearGradient id="ps-metal" x1="0" x2="1"><stop offset="0" stop-color="#9ca3af" /><stop offset=".5" stop-color="#f3f4f6" /><stop offset="1" stop-color="#6b7280" /></linearGradient>
      <radialGradient id="ps-spark"><stop offset="0" stop-color="#a5b4fc" /><stop offset="1" stop-color="#a5b4fc" stop-opacity="0" /></radialGradient>
    </defs>
    <circle class="spark" cx="125" cy="226" r="16" fill="url(#ps-spark)" />
    <g class="plug">
      <path d={CORD} fill="none" stroke="#111827" stroke-width="6" stroke-linecap="round" />
      <path d={CORD} fill="none" stroke="#4b5563" stroke-width="2" stroke-linecap="round" opacity=".6" transform="translate(-1.5 0)" />
      <path class="okline" d={CORD} fill="none" stroke="#22c55e" stroke-width="6" stroke-linecap="round" />
      <path class="pulse" d={CORD} fill="none" stroke="#a5b4fc" stroke-width="3.5" stroke-linecap="round" />
      <path d="M119 254 L131 254 L129.5 270 Q125 273 120.5 270 Z" fill="#1f2937" />
      <path d="M120 259 h10 M120.4 263 h9.2 M120.8 267 h8.4" stroke="#0b0f17" stroke-width="1" />
      <rect x="113" y="226" width="24" height="30" rx="6" fill="url(#ps-boot)" />
      <rect x="115" y="228" width="3" height="26" rx="1.5" fill="#fff" opacity=".12" />
      <circle class="led" cx="125" cy="249" r="1.8" />
      <rect x="118" y="215" width="14" height="12" rx="3.5" fill="url(#ps-metal)" />
      <rect x="120.5" y="217" width="9" height="2.2" rx="1.1" fill="#4b5563" opacity=".7" />
    </g>
  </svg>
</div>

<style>
  .stage { position: relative; width: 250px; height: 350px; flex: none; overflow: hidden; border-radius: 16px;
    background: radial-gradient(180px 160px at 50% 42%, var(--color-surface) 0%, transparent 70%); }
  .phone { position: absolute; left: 69px; top: 10px; width: 112px; height: 216px; border-radius: 22px; padding: 6px; z-index: 3;
    background: linear-gradient(145deg, #374151, #111827);
    box-shadow: 0 22px 40px -18px rgb(17 24 39 / .55), inset 0 0 0 1px rgb(255 255 255 / .08); }
  .phone::before, .phone::after { content: ""; position: absolute; right: -1.5px; width: 1.5px; border-radius: 0 1px 1px 0; background: #4b5563; }
  .phone::before { top: 46px; height: 20px; }
  .phone::after { top: 74px; height: 11px; }
  .port { position: absolute; left: 50%; bottom: -1px; width: 18px; height: 4px; margin-left: -9px; border-radius: 3px; background: #030712; }
  .screen { position: relative; width: 100%; height: 100%; border-radius: 17px; background: #0b1220; overflow: hidden; }
  .screen::after { content: ""; position: absolute; top: 7px; left: 50%; width: 7px; height: 7px; margin-left: -3.5px; border-radius: 50%; background: #000; box-shadow: 0 0 0 1.5px #1f2937; }
  .view { position: absolute; inset: 0; display: grid; place-items: center; opacity: 0; transform: scale(.92);
    transition: opacity .45s cubic-bezier(.2, .8, .2, 1), transform .45s cubic-bezier(.2, .8, .2, 1); }
  .view.shown { opacity: 1; transform: none; }
  .lock b { font-size: 22px; font-weight: 300; color: #475569; }
  .ok { background: linear-gradient(160deg, #1e3a8a, #0b1220); }
  .check { width: 54px; height: 54px; border-radius: 50%; background: #16a34a; display: grid; place-items: center; color: #fff; font-size: 28px; font-weight: 800; }
  .shown .check { animation: pop-in .5s cubic-bezier(.2, .8, .2, 1); }
  .dlg { width: 86px; background: #fff; border-radius: 9px; padding: 7px; font-size: 8.5px; color: #111; line-height: 1.3; }
  .allow { margin-top: 6px; background: #4f46e5; color: #fff; text-align: center; border-radius: 6px; padding: 3px; font-weight: 700; animation: tap 1.4s infinite; }
  .ring { position: absolute; left: 40px; top: 33px; width: 170px; height: 170px; border-radius: 50%; border: 2px solid var(--color-accent); opacity: 0; z-index: 1; }
  .cable { position: absolute; inset: 0; z-index: 2; overflow: visible; }
  .plug { transition: transform .7s cubic-bezier(.3, 1.3, .5, 1); }
  .pulse { stroke-dasharray: 3 16; opacity: 0; transition: opacity .3s; }
  .okline, .spark { opacity: 0; }
  .okline { transition: opacity .5s .2s; }
  .spark { transform-origin: 125px 226px; }
  .led { fill: #9ca3af; transition: fill .3s; }
  [data-state="wait"] .plug { transform: translateY(24px); animation: hover 2.2s ease-in-out infinite; }
  [data-state="auth"] .ring { animation: ring 1.8s ease-out infinite; }
  [data-state="auth"] .pulse { opacity: 1; animation: flow .7s linear infinite; }
  [data-state="auth"] .spark { animation: spark .6s ease-out 1; }
  [data-state="auth"] .led { fill: #818cf8; }
  [data-state="ok"] .ring { border-color: var(--color-ok); animation: ring 1.6s ease-out 2; }
  [data-state="ok"] .okline { opacity: .85; }
  [data-state="ok"] .led { fill: #4ade80; }
  @keyframes hover { 0%, 100% { transform: translateY(24px); } 50% { transform: translateY(32px); } }
  @keyframes flow { to { stroke-dashoffset: -19; } }
  @keyframes spark { 0% { opacity: .9; transform: scale(.2); } 100% { opacity: 0; transform: scale(1.6); } }
</style>
