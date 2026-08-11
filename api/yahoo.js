const MARKETS = [
  { symbol: "GC=F", name: "Gold futures", asset_class: "commodity" },
  { symbol: "SI=F", name: "Silver futures", asset_class: "commodity" },
  { symbol: "CL=F", name: "Crude oil futures", asset_class: "commodity" },
  { symbol: "AUDUSD=X", name: "AUD / USD", asset_class: "fx" },
  { symbol: "^GSPC", name: "S&P 500", asset_class: "index" },
  { symbol: "^AXJO", name: "ASX 200", asset_class: "index" },
  { symbol: "BHP.AX", name: "BHP Group", asset_class: "equity" },
];

async function chart(definition) {
  const symbol = encodeURIComponent(definition.symbol);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1h&range=60d&includePrePost=false&events=div%2Csplits`;
  const result = await fetch(url, {
    headers: {
      accept: "application/json",
      "user-agent": "Mozilla/5.0 aussie-agent-fleet-monitor/1.0",
    },
    signal: AbortSignal.timeout(7000),
  });
  if (!result.ok) throw new Error(`Yahoo HTTP ${result.status}`);
  const payload = await result.json();
  if (payload.chart?.error) throw new Error(payload.chart.error.description || "Yahoo chart error");

  const data = payload.chart?.result?.[0];
  if (!data?.meta || !Array.isArray(data.timestamp)) throw new Error("Yahoo chart data missing");
  const quote = data.indicators?.quote?.[0] || {};
  const candles = data.timestamp.flatMap((time, index) => {
    const open = Number(quote.open?.[index]);
    const high = Number(quote.high?.[index]);
    const low = Number(quote.low?.[index]);
    const close = Number(quote.close?.[index]);
    return [time, open, high, low, close].every(Number.isFinite)
      ? [{ time: Number(time), open, high, low, close }]
      : [];
  }).slice(-180);
  if (!candles.length) throw new Error("Yahoo candles missing");

  const meta = data.meta;
  const last = Number(meta.regularMarketPrice ?? candles.at(-1).close);
  const previous = Number(meta.chartPreviousClose ?? meta.previousClose);
  const sourceTime = Number(meta.regularMarketTime || candles.at(-1).time);
  return {
    ...definition,
    last,
    currency: meta.currency || "",
    exchange: meta.fullExchangeName || meta.exchangeName || "Yahoo Finance",
    change_pct: Number.isFinite(previous) && previous !== 0 ? (last - previous) / previous * 100 : null,
    high_24h: Number.isFinite(Number(meta.regularMarketDayHigh)) ? Number(meta.regularMarketDayHigh) : null,
    low_24h: Number.isFinite(Number(meta.regularMarketDayLow)) ? Number(meta.regularMarketDayLow) : null,
    source: "Yahoo Finance",
    source_ts: sourceTime,
    age_seconds: Math.max(0, Math.round(Date.now() / 1000 - sourceTime)),
    delayed: true,
    candles,
  };
}

export default async function handler(request, response) {
  if (request.method !== "GET") {
    response.setHeader("Allow", "GET");
    return response.status(405).json({ error: "method_not_allowed" });
  }

  const settled = await Promise.allSettled(MARKETS.map(chart));
  const markets = settled.filter(item => item.status === "fulfilled").map(item => item.value);
  const failures = settled.flatMap((item, index) => item.status === "rejected"
    ? [{ symbol: MARKETS[index].symbol, reason: item.reason?.message || "unavailable" }]
    : []);
  if (!markets.length) {
    response.setHeader("Cache-Control", "no-store");
    return response.status(502).json({ error: "yahoo_market_unavailable", failures });
  }

  response.setHeader("Cache-Control", "public, s-maxage=30, stale-while-revalidate=120");
  return response.status(200).json({
    status: failures.length ? "partial" : "market_only",
    source: "Yahoo Finance public chart data",
    observed_at: new Date().toISOString(),
    delayed: true,
    quality: {
      requested: MARKETS.length,
      received: markets.length,
      failures,
      stale: markets.filter(item => item.age_seconds > 3600).map(item => item.symbol),
    },
    markets,
  });
}
