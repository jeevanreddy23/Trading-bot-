import assert from "node:assert/strict";
import fs from "node:fs";

const symbols = ["BTC/AUD", "ETH/AUD", "SOL/AUD"];
const ticker = Object.fromEntries(symbols.map((symbol, index) => [symbol, {
  a: [String(100 + index + 0.2)], b: [String(100 + index)], c: [String(100 + index + 0.1)],
  h: ["110", "111"], l: ["90", "89"], o: "95", v: ["10", "20"],
}]));

globalThis.fetch = async input => {
  const url = new URL(input);
  if (url.hostname === "query1.finance.yahoo.com") {
    const symbol = decodeURIComponent(url.pathname.split("/").at(-1));
    const offset = ["GC=F", "SI=F", "CL=F", "AUDUSD=X", "^GSPC", "^AXJO", "BHP.AX"].indexOf(symbol);
    return {
      ok: true,
      json: async () => ({ chart: { error: null, result: [{
        meta: {
          symbol, currency: symbol.endsWith(".AX") || symbol === "^AXJO" ? "AUD" : "USD",
          fullExchangeName: "Test Exchange", regularMarketPrice: 200 + offset,
          chartPreviousClose: 190 + offset, regularMarketTime: 1786440000,
          regularMarketDayHigh: 210 + offset, regularMarketDayLow: 180 + offset,
        },
        timestamp: [1786436400, 1786440000],
        indicators: { quote: [{
          open: [198 + offset, 199 + offset], high: [201 + offset, 202 + offset],
          low: [197 + offset, 198 + offset], close: [200 + offset, 201 + offset],
        }] },
      }] } }),
    };
  }
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

const yahooSource = fs.readFileSync(new URL("../api/yahoo.js", import.meta.url), "utf8");
const yahooModuleUrl = `data:text/javascript;base64,${Buffer.from(yahooSource).toString("base64")}`;
const { default: yahooHandler } = await import(yahooModuleUrl);
const yahooReply = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, status(code) { this.code = code; return this; }, json(body) { this.body = body; return this; } };
await yahooHandler({ method: "GET" }, yahooReply);
assert.equal(yahooReply.code, 200);
assert.equal(yahooReply.body.status, "market_only");
assert.equal(yahooReply.body.delayed, true);
assert.equal(yahooReply.body.quality.requested, 7);
assert.equal(yahooReply.body.quality.received, 7);
assert.deepEqual(yahooReply.body.markets.map(row => row.symbol), ["GC=F", "SI=F", "CL=F", "AUDUSD=X", "^GSPC", "^AXJO", "BHP.AX"]);
assert.equal(yahooReply.body.markets[0].source, "Yahoo Finance");
assert.equal(yahooReply.body.markets[0].candles.length, 2);
assert.match(yahooReply.headers["Cache-Control"], /s-maxage=30/);

const html = fs.readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const inline = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(inline);
new Function(inline);
assert.match(html, /wss:\/\/ws\.kraken\.com\/v2/);
assert.match(html, /\/api\/yahoo/);
assert.match(html, /6 fleet agents/);
console.log("Kraken, Yahoo and portal checks passed");
