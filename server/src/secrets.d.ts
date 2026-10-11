// Sekrety Workera (`npx wrangler secret put QUOTA_KEY -c wrangler.jsonc`) — `wrangler types` ich nie zna.
interface Env {
  QUOTA_KEY: string; // klucz HMAC dla liczników limitu na adres (src/quota.ts)
}
declare namespace Cloudflare {
  interface Env {
    QUOTA_KEY: string;
  }
}
