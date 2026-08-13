const SYMBOLS = ["BTC/AUD", "ETH/AUD", "SOL/AUD"];
const KRAKEN = "https://api.kraken.com/0/public";

async function kraken(path) {
  const response = await fetch(`${KRAKEN}/${path}`, {
    headers: { accept: "application/json", "user-agent": "aussie-agent-fleet-monitor/1.0" },
    signal: AbortSignal.timeout(7000),
  });
  if (!response.ok) throw new Error(`Kraken HTTP ${response.status}`);
  const body = await response.json();
  if (body.error?.length) throw new Error(body.error.join(", "));
  return body.result;
}

export default async function handler(request, response) {
  if (request.method !== "GET") {
    response.setHeader("Allow", "GET");
    return response.status(405).json({ error: "method_not_allowed" });
  }

  try {
    const pair = encodeURIComponent(SYMBOLS.join(","));
    const [tickers, ...ohlc] = await Promise.all([
      kraken(`Ticker?pair=${pair}&assetVersion=1`),
      ...SYMBOLS.map(symbol => kraken(
        `OHLC?pair=${encodeURIComponent(symbol)}&interval=60&assetVersion=1`
      )),
    ]);
    const markets = SYMBOLS.map((symbol, index) => {
      const ticker = tickers[symbol];
      const rows = ohlc[index][symbol] || [];
      const bid = Number(ticker.b[0]), ask = Number(ticker.a[0]);
      const open = Number(ticker.o), last = Number(ticker.c[0]);
      return {
        symbol, last, bid, ask,
        spread_pct: (ask - bid) / ((ask + bid) / 2) * 100,
        change_pct: open ? (last - open) / open * 100 : 0,
        high_24h: Number(ticker.h[1]), low_24h: Number(ticker.l[1]),
        volume_24h: Number(ticker.v[1]),
        candles: rows.slice(-180).map(row => ({
          time: Number(row[0]), open: Number(row[1]), high: Number(row[2]),
          low: Number(row[3]), close: Number(row[4]),
        })),
      };
    });
    response.setHeader("Cache-Control", "public, s-maxage=5, stale-while-revalidate=15");
    return response.status(200).json({
      status: "market_only", source: "Kraken public REST", observed_at: new Date().toISOString(), markets,
    });
  } catch (error) {
    response.setHeader("Cache-Control", "no-store");
    return response.status(502).json({ error: "kraken_market_unavailable", detail: error.message });
  }
}
