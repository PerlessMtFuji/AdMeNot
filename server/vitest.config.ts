import { fileURLToPath } from "node:url";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

const migrations = fileURLToPath(new URL("./migrations", import.meta.url));

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.jsonc" },
      // Migracje jako wiązanie tylko dla testów — stosuje je test/apply-migrations.ts.
      miniflare: { bindings: { TEST_MIGRATIONS: await readD1Migrations(migrations) } },
    })),
  ],
  test: { setupFiles: ["./test/apply-migrations.ts"] },
});
