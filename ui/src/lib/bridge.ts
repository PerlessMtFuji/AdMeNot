import type { Api, ApiError, EventMap, EventName } from './types';

export interface Bridge {
  api: Api;
  on<K extends EventName>(name: K, handler: (detail: EventMap[K]) => void): () => void;
}

type PywebviewWindow = Window & { pywebview?: { api: Api } };

export function isApiError(value: unknown): value is ApiError {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  // Kilka wyników (np. DevicesPayload) ma też pole `error`, ale jako string | null,
  // nie jako obiekt ApiErrorBody — więc samo `'error' in value` nie wystarcza.
  const error = (value as { error: unknown }).error;
  return typeof error === 'object' && error !== null;
}

function waitForPywebview(): Promise<Api> {
  const w = window as PywebviewWindow;
  return new Promise((resolve) => {
    if (w.pywebview?.api) {
      resolve(w.pywebview.api);
      return;
    }
    window.addEventListener('pywebviewready', () => resolve(w.pywebview!.api), { once: true });
  });
}

function windowEvents(): Bridge['on'] {
  return (name, handler) => {
    const listener = (e: Event) => handler((e as CustomEvent).detail);
    window.addEventListener(`admenot:${name}`, listener);
    return () => window.removeEventListener(`admenot:${name}`, listener);
  };
}

export async function connectBridge(): Promise<Bridge> {
  // W buildzie produkcyjnym stała jest pusta i import atrapy znika z paczki.
  if (import.meta.env.VITE_FAKE_BRIDGE === '1' && !(window as PywebviewWindow).pywebview) {
    const { createFakeBridge } = await import('./fakeBridge');
    const scenario = new URLSearchParams(location.search).get('scenario') ?? 'adware';
    return createFakeBridge(scenario);
  }
  return { api: await waitForPywebview(), on: windowEvents() };
}
