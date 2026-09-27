import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { connectBridge } from './lib/bridge';
import { Controller } from './lib/controller';
import { AppState } from './lib/state.svelte';

const state = new AppState();
window.addEventListener('error', (e) => { state.fatal = String(e.message || e.error); });
window.addEventListener('unhandledrejection', (e) => { state.fatal = String(e.reason); });

const bridge = await connectBridge();
const ctl = new Controller(state, bridge);
if (import.meta.env.VITE_FAKE_BRIDGE === '1') {
  (window as unknown as { __demalware: unknown }).__demalware = { ctl, bridge };
}
mount(App, { target: document.getElementById('app')!, props: { ctl } });
void ctl.init();
