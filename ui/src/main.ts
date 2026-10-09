import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { connectBridge } from './lib/bridge';
import { Controller } from './lib/controller';
import { AppState } from './lib/state.svelte';

const state = new AppState();
let ctl: Controller | null = null;
// Błąd interfejsu: ekran „fatal” i jeden raport do wysłania (spec raportów §3.1 pkt 2).
function fail(message: string, error: unknown): void {
  if (!state.fatal) state.fatal = message; // kaskada błędów: ekran nie migocze
  void ctl?.captureUiError(message, error instanceof Error ? error.stack ?? null : null);
}
window.addEventListener('error', (e) => fail(String(e.message || e.error), e.error));
window.addEventListener('unhandledrejection', (e) => fail(String(e.reason), e.reason));

const bridge = await connectBridge();
ctl = new Controller(state, bridge);
if (import.meta.env.VITE_FAKE_BRIDGE === '1') {
  (window as unknown as { __admenot: unknown }).__admenot = { ctl, bridge };
}
mount(App, { target: document.getElementById('app')!, props: { ctl } });
void ctl.init();
