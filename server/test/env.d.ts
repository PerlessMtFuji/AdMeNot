import type { D1Migration } from "cloudflare:test";

// W zainstalowanej wersji wtyczki `env` z cloudflare:workers ma typ Cloudflare.Env
// (brak ProvidedEnv), więc wiązanie testowe dopisujemy do niego.
declare global {
  namespace Cloudflare {
    interface Env {
      TEST_MIGRATIONS: D1Migration[];
    }
  }
}
