import assert from "node:assert/strict";
import fs from "node:fs";

const symbols = ["BTC/AUD", "ETH/AUD", "SOL/AUD"];
const ticker = Object.fromEntries(symbols.map((symbol, index) => [symbol, {
  a: [String(100 + index + 0.2)], b: [String(100 + index)], c: [String(100 + index + 0.1)],
  h: ["110", "111"], l: ["90", "89"], o: "95", v: ["10", "20"],
}]));

globalThis.fetch = async input => {
  const url = new URL(input);
  const isTicker = url.pathname.endsWith("/Ticker");
  const symbol = url.searchParams.get("pair");
  return {
    ok: true,
    json: async () => ({ error: [], result: isTicker ? ticker : {
      [symbol]: [[1786440000, "99", "102", "98", "101", "100", "2", 5]], last: 1786440000,
    }}),
  };
};

const source = fs.readFileSync(new URL("../api/market.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { default: handler } = await import(moduleUrl);
const reply = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, status(code) { this.code = code; return this; }, json(body) { this.body = body; return this; } };
await handler({ method: "GET" }, reply);
assert.equal(reply.code, 200);
assert.equal(reply.body.status, "market_only");
assert.deepEqual(reply.body.markets.map(row => row.symbol), symbols);
assert.equal(reply.body.markets[0].candles[0].close, 101);
assert.match(reply.headers["Cache-Control"], /s-maxage=5/);

const html = fs.readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const inline = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(inline);
new Function(inline);
assert.match(html, /wss:\/\/ws\.kraken\.com\/v2/);
console.log("market API and portal checks passed");
