export default async function handler(request, response) {
  if (request.method !== "GET") {
    response.setHeader("Allow", "GET");
    return response.status(405).json({ error: "method_not_allowed" });
  }

  const origin = process.env.MONITOR_ORIGIN?.replace(/\/$/, "");
  const token = process.env.MONITOR_TOKEN;
  if (!origin || !token) {
    return response.status(503).json({ error: "monitor_not_configured" });
  }

  try {
    const upstream = await fetch(`${origin}/v1/status`, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(7000),
      cache: "no-store",
    });
    const body = await upstream.text();
    response.setHeader("Cache-Control", "no-store, max-age=0");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    return response.status(upstream.status).send(body);
  } catch {
    return response.status(502).json({ error: "monitor_unreachable" });
  }
}
