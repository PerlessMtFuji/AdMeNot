import { render } from '@testing-library/svelte';
import { createRawSnippet, type Component, type Snippet } from 'svelte';
import { Controller } from './lib/controller';
import { createFakeBridge } from './lib/fakeBridge';
import { AppState } from './lib/state.svelte';

export async function setupCtl(scenario = 'empty') {
  const bridge = createFakeBridge(scenario, { delay: 0 });
  const ctl = new Controller(new AppState(), bridge);
  await ctl.init();
  return { ctl, s: ctl.state, bridge };
}

export async function renderWith(component: Component<any>, scenario = 'empty',
  props: Record<string, unknown> = {}) {
  const env = await setupCtl(scenario);
  const view = render(component, { props, context: new Map([['ctl', env.ctl]]) });
  return { ...view, ...env };
}

/** Snippet z czystego HTML do testów komponentów przyjmujących children/actions. */
export function snippet(html: string): Snippet {
  return createRawSnippet(() => ({ render: () => `<span>${html}</span>` }));
}
