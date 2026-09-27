/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FAKE_BRIDGE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
