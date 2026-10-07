// Worker AdMeNot: statyczna strona z public/ (bez kodu) + API pod /api/v1/ (spec backendu §2).
// Nie logujemy zapytań ani nagłówków — adresów IP nie zapisujemy nigdzie (§2.2).

const JSON_HEADERS = { "Content-Type": "application/json", "Cache-Control": "no-store" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function health(env: Env): Promise<Response> {
  try {
    await env.DB.prepare("SELECT 1").first();
    return json({ ok: true, db: true });
  } catch {
    return json({ ok: false, db: false }, 503);
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (request.method === "GET" && pathname === "/api/v1/health") {
      return health(env);
    }
    return json({ error: "not_found" }, 404);
  },
} satisfies ExportedHandler<Env>;
