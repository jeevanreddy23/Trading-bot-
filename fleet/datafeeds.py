"""Data layer.

FeedRouter picks the best available provider per market class:
  - ccxt      -> live crypto quotes/candles from real exchanges (multi-venue)
  - yahoo     -> stocks / commodities futures / FX (yfinance)
  - stooq     -> daily-bar fallback for stocks/commodities/FX (free CSV)
  - sim       -> deterministic synthetic market for offline testing & demos

Every Quote carries its source so nothing synthetic can masquerade as live.
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import dig
from .util import market_of


@dataclass
class Quote:
    last: float
    bid: float | None = None
    ask: float | None = None
    ts: float = 0.0
    source: str = "?"


class KrakenStreamProvider:
    """Reads the atomic public WebSocket snapshot written by kraken_ws.py."""

    def __init__(self, path: str, max_age: float = 45.0):
        self.path = path
        self.max_age = max_age
        self.payload: dict = {}

    def refresh(self) -> bool:
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if time.time() - float(payload.get("received_ts", 0)) > self.max_age:
                return False
            if payload.get("error"):
                return False
            self.payload = payload
            return True
        except (OSError, ValueError, TypeError):
            return False

    def quote(self, symbol: str) -> Quote | None:
        row = self.payload.get("quotes", {}).get(symbol)
        book = self.payload.get("books", {}).get(symbol, {})
        if not row or book.get("checksum_valid") is not True:
            return None
        return Quote(float(row["last"]), float(row["bid"]), float(row["ask"]),
                     float(row["received_ts"]), "kraken-ws")

    def ohlcv(self, symbol: str, bars: int = 250) -> pd.DataFrame | None:
        rows = self.payload.get("candles", {}).get(symbol, [])[-bars:]
        if len(rows) < 60:
            return None
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
        frame.attrs["source"] = "kraken-ws"
        return frame


# --- synthetic market seed levels (only used by the sim provider; real feeds override) ---
SIM_BASE = {
    "BTC/USDT": 118000.0, "ETH/USDT": 4400.0, "SOL/USDT": 210.0,
    "BHP.AX": 43.0, "CBA.AX": 165.0, "CSL.AX": 265.0, "WES.AX": 78.0, "FMG.AX": 19.5,
    "AAPL": 235.0, "MSFT": 520.0, "NVDA": 175.0, "SPY": 640.0, "QQQ": 575.0,
    "GC=F": 3350.0, "SI=F": 38.0, "CL=F": 66.0, "HG=F": 4.6, "ZW=F": 5.4, "NG=F": 2.9,
    "AUDUSD=X": 0.655, "EURUSD=X": 1.17, "USDJPY=X": 147.0, "GBPUSD=X": 1.34,
}
SIM_VOL = {"crypto": 0.60, "stocks": 0.18, "commodities": 0.25, "fx": 0.09}
YEAR_SEC = 365 * 24 * 3600


class SimProvider:
    """Regime-switching random walk + per-venue bases with occasional transient
    dislocations, so the arb scanner has realistic (mostly fee-negative) work."""

    def __init__(self, seed: int = 42, accel: float = 4.0):
        self.rng = random.Random(seed)
        self.accel = accel
        self.prices = dict(SIM_BASE)
        self.drift = {s: self.rng.uniform(-0.5, 0.8) for s in SIM_BASE}
        self.venue_basis: dict = {}
        self.dislocation: dict = {}
        self.last_step = time.time()
        self.hist_cache: dict = {}

    def _ensure(self, symbol: str):
        if symbol not in self.prices:
            self.prices[symbol] = 100.0
            self.drift[symbol] = 0.0

    def step(self, venues: list, arb_symbols: list):
        dt = max(1.0, time.time() - self.last_step) / YEAR_SEC
        self.last_step = time.time()
        for s in list(self.prices):
            vol = SIM_VOL[market_of(s)]
            if self.rng.random() < 0.01:
                self.drift[s] = self.rng.uniform(-0.8, 1.0)
            z = self.rng.gauss(0, 1)
            self.prices[s] *= math.exp((self.drift[s] - 0.5 * vol * vol) * dt
                                       + vol * math.sqrt(dt) * z * self.accel)
        for s in arb_symbols:
            for v in venues:
                k = (s, v)
                if k not in self.venue_basis:
                    self.venue_basis[k] = self.rng.uniform(-6, 6)
                bps, left = self.dislocation.get(k, (0.0, 0))
                if left <= 0 and self.rng.random() < 0.06:
                    self.dislocation[k] = (self.rng.choice([-1, 1]) * self.rng.uniform(20, 90),
                                           self.rng.randint(2, 4))
                elif left > 0:
                    self.dislocation[k] = (bps * 0.55, left - 1)

    def quote(self, symbol: str) -> Quote:
        self._ensure(symbol)
        px = self.prices[symbol]
        half = px * 0.0002
        return Quote(px, px - half, px + half, time.time(), "sim")

    def venue_quote(self, symbol: str, venue: str) -> Quote:
        self._ensure(symbol)
        base = self.prices[symbol]
        bps = (self.venue_basis.get((symbol, venue), 0.0)
               + self.dislocation.get((symbol, venue), (0.0, 0))[0]
               + self.rng.gauss(0, 2))
        px = base * (1 + bps / 1e4)
        half = px * 0.0003
        return Quote(px, px - half, px + half, time.time(), f"sim:{venue}")

    def ohlcv(self, symbol: str, timeframe: str = "1d", bars: int = 250) -> pd.DataFrame:
        self._ensure(symbol)
        key = (symbol, timeframe, bars)
        if key in self.hist_cache:
            df = self.hist_cache[key].copy()
            df.loc[df.index[-1], "close"] = self.prices[symbol]   # keep last bar anchored
            return df
        rng = random.Random((hash((symbol, timeframe)) & 0xFFFF) + 7)
        vol = SIM_VOL[market_of(symbol)]
        step = 1 / (365 * 24) if timeframe == "1h" else 1 / 365
        n = bars
        drift = rng.uniform(-0.3, 0.6)
        rets = []
        for _ in range(n):
            if rng.random() < 0.02:
                drift = rng.uniform(-0.8, 1.0)
            rets.append((drift - 0.5 * vol * vol) * step + vol * math.sqrt(step) * rng.gauss(0, 1))
        path = np.exp(np.cumsum(rets))
        path = path / path[-1] * self.prices[symbol]
        close = pd.Series(path)
        openp = close.shift(1).fillna(close.iloc[0])
        wig = np.array([abs(rng.gauss(0, vol * math.sqrt(step))) for _ in range(n)])
        high = np.maximum(openp.to_numpy(), close.to_numpy()) * (1 + wig)
        low = np.minimum(openp.to_numpy(), close.to_numpy()) * (1 - wig)
        freq = "h" if timeframe == "1h" else "D"
        idx = pd.date_range(end=pd.Timestamp.utcnow().floor(freq), periods=n, freq=freq)
        df = pd.DataFrame({"open": openp.to_numpy(), "high": high, "low": low,
                           "close": close.to_numpy(), "volume": 1000.0}, index=idx)
        df.attrs["source"] = "sim"
        self.hist_cache[key] = df
        return df.copy()


class CcxtProvider:
    def __init__(self, venues: list):
        import ccxt  # lazy
        self.ccxt = ccxt
        self.venues = venues
        self.ex: dict = {}

    def _get(self, venue: str):
        if venue not in self.ex:
            klass = getattr(self.ccxt, venue, None)
            if klass is None:
                self.ex[venue] = None
            else:
                try:
                    inst = klass({"enableRateLimit": True, "timeout": 8000})
                    inst.load_markets()
                    self.ex[venue] = inst
                except Exception:
                    self.ex[venue] = None
        return self.ex[venue]

    def available(self) -> bool:
        try:
            ex = self._get(self.venues[0] if self.venues else "kraken")
            return ex is not None and bool(ex.markets)
        except Exception:
            return False

    def venue_quotes(self, symbols: list) -> dict:
        out = {}
        for v in self.venues:
            ex = self._get(v)
            if ex is None:
                continue
            for s in symbols:
                if s not in ex.markets:
                    continue
                try:
                    t = ex.fetch_ticker(s)
                    out[(s, v)] = Quote(t.get("last") or t.get("close"),
                                        t.get("bid"), t.get("ask"), time.time(), v)
                except Exception:
                    continue
        return out

    def ohlcv(self, symbol: str, timeframe: str = "1h", bars: int = 200) -> pd.DataFrame | None:
        for v in self.venues:
            ex = self._get(v)
            if ex is None or symbol not in getattr(ex, "markets", {}):
                continue
            try:
                raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=bars)
                if not raw:
                    continue
                df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
                df.index = pd.to_datetime(df.pop("ts"), unit="ms")
                df.attrs["source"] = v
                return df
            except Exception:
                continue
        return None


class YahooProvider:
    def __init__(self):
        import yfinance as yf  # lazy
        self.yf = yf
        self._daily: dict = {}
        self._last: dict = {}

    def available(self) -> bool:
        try:
            h = self.yf.Ticker("AAPL").history(period="5d")
            return len(h) > 0
        except Exception:
            return False

    def last(self, symbol: str, max_age: float = 60.0) -> Quote | None:
        cached = self._last.get(symbol)
        if cached and time.time() - cached.ts < max_age:
            return cached
        try:
            t = self.yf.Ticker(symbol)
            px = None
            try:
                px = float(t.fast_info["last_price"])
            except Exception:
                h = t.history(period="5d")
                if len(h):
                    px = float(h["Close"].iloc[-1])
            if not px:
                return None
            q = Quote(px, None, None, time.time(), "yahoo")
            self._last[symbol] = q
            return q
        except Exception:
            return None

    def ohlcv(self, symbol: str, timeframe: str = "1d", bars: int = 260) -> pd.DataFrame | None:
        key = (symbol, timeframe)
        cached = self._daily.get(key)
        if cached and time.time() - cached[0] < 1800:
            return cached[1]
        try:
            if timeframe == "1h":
                h = self.yf.Ticker(symbol).history(period="60d", interval="1h")
            else:
                h = self.yf.Ticker(symbol).history(period="2y", interval="1d")
            if not len(h):
                return None
            df = h.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                   "Close": "close", "Volume": "volume"})
            df = df[["open", "high", "low", "close", "volume"]].tail(bars)
            df.attrs["source"] = "yahoo"
            self._daily[key] = (time.time(), df)
            return df
        except Exception:
            return None


class StooqProvider:
    """Daily bars only — free CSV endpoint, used as a fallback."""

    MAP_F = {"GC=F": "gc.f", "SI=F": "si.f", "CL=F": "cl.f", "HG=F": "hg.f",
             "ZW=F": "zw.f", "NG=F": "ng.f"}

    def __init__(self):
        import requests
        self.requests = requests
        self._cache: dict = {}

    def _code(self, symbol: str) -> str | None:
        if symbol in self.MAP_F:
            return self.MAP_F[symbol]
        if symbol.endswith("=X"):
            return symbol[:6].lower()
        if symbol.endswith(".AX"):
            return symbol[:-3].lower() + ".au"
        if symbol.isalpha():
            return symbol.lower() + ".us"
        return None

    def available(self) -> bool:
        return self.ohlcv("AUDUSD=X") is not None

    def ohlcv(self, symbol: str, timeframe: str = "1d", bars: int = 260) -> pd.DataFrame | None:
        if timeframe != "1d":
            return None
        code = self._code(symbol)
        if not code:
            return None
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[0] < 3600:
            return cached[1]
        try:
            r = self.requests.get(f"https://stooq.com/q/d/l/?s={code}&i=d", timeout=10)
            if r.status_code != 200 or "Date" not in r.text[:100]:
                return None
            df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"], index_col="Date")
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].tail(bars)
            df.attrs["source"] = "stooq"
            self._cache[symbol] = (time.time(), df)
            return df
        except Exception:
            return None


class FeedRouter:
    def __init__(self, cfg: dict, force_sim: bool = False, quiet: bool = False):
        self.cfg = cfg
        self.quotes: dict = {}          # canonical symbol -> Quote; (symbol, venue) -> Quote
        self.simulated = False
        self.source_status: dict = {}

        m = cfg["markets"]
        self.crypto_venues = m["crypto"].get("venues", []) if m["crypto"].get("enabled") else []
        self.arb_symbols = m["crypto"].get("arb_symbols", []) if m["crypto"].get("enabled") else []
        self.crypto_symbols = sorted(set(self.arb_symbols) | set(m["crypto"].get("momentum_symbols", []))) \
            if m["crypto"].get("enabled") else []
        self.enabled_slow_symbols = []  # configured stocks + commodities + fx
        if m["stocks"].get("enabled"):
            self.enabled_slow_symbols += m["stocks"].get("asx", []) + m["stocks"].get("us", [])
        if m["commodities"].get("enabled"):
            self.enabled_slow_symbols += m["commodities"].get("symbols", [])
        fx_syms = m["fx"].get("symbols", []) if m["fx"].get("enabled") else []
        self.enabled_slow_symbols += fx_syms
        self.slow_symbols = list(self.enabled_slow_symbols)
        for must in ("AUDUSD=X", "USDJPY=X"):    # always needed for AUD conversion
            if must not in self.slow_symbols:
                self.slow_symbols.append(must)

        self.sim = SimProvider(dig(cfg, "data.sim_seed", 42), dig(cfg, "data.sim_accel", 4))
        stream_path = dig(cfg, "data.kraken_ws_snapshot", os.getenv(
            "KRAKEN_WS_OUTPUT", os.path.join(dig(cfg, "loop.state_dir", "state"), "kraken_stream.json")))
        self.kraken_ws = KrakenStreamProvider(
            stream_path, float(dig(cfg, "data.max_quote_age_seconds", 45)))
        self.ccxt_p = None
        self.yahoo_p = None
        self.stooq_p = None

        if not force_sim:
            try:
                p = CcxtProvider(self.crypto_venues)
                if p.available():
                    self.ccxt_p = p
            except Exception:
                pass
            try:
                p = YahooProvider()
                if p.available():
                    self.yahoo_p = p
            except Exception:
                pass
            if self.yahoo_p is None:
                try:
                    p = StooqProvider()
                    if p.available():
                        self.stooq_p = p
                except Exception:
                    pass

        ws_ready = self.kraken_ws.refresh()
        crypto_needs_sim = bool(self.crypto_symbols) and self.ccxt_p is None and not ws_ready
        slow_needs_sim = bool(self.enabled_slow_symbols) and self.yahoo_p is None and self.stooq_p is None
        self.simulated = force_sim or crypto_needs_sim or slow_needs_sim
        self.source_status = {
            "crypto": "kraken-ws (live, CRC32)" if ws_ready else (
                "ccxt (live)" if self.ccxt_p else "sim (synthetic)"),
            "stocks/commodities": "yahoo (live)" if self.yahoo_p else ("stooq (daily)" if self.stooq_p else "sim (synthetic)"),
            "fx": "yahoo (live)" if self.yahoo_p else ("stooq (daily)" if self.stooq_p else "sim (synthetic)"),
        }
        if not quiet:
            print(f"[feeds] sources: {self.source_status}")

    # ---------- refresh ----------
    def refresh(self):
        ws_ready = self.kraken_ws.refresh()
        if ws_ready:
            for symbol in self.crypto_symbols:
                quote = self.kraken_ws.quote(symbol)
                if quote:
                    self.quotes[symbol] = quote
                    self.quotes[(symbol, "kraken")] = quote
            self.source_status["crypto"] = "kraken-ws (live, CRC32)"
        if self.ccxt_p:
            vq = self.ccxt_p.venue_quotes(self.arb_symbols or self.crypto_symbols)
            self.quotes.update(vq)
            for s in self.crypto_symbols:                       # canonical = first venue seen
                if ws_ready and self.quotes.get(s, Quote(0)).source == "kraken-ws":
                    continue
                for v in self.crypto_venues:
                    q = vq.get((s, v))
                    if q:
                        self.quotes[s] = q
                        break
        if self.yahoo_p:
            for s in self.slow_symbols:
                q = self.yahoo_p.last(s)
                if q:
                    self.quotes[s] = q
        elif self.stooq_p:
            for s in self.slow_symbols:
                df = self.stooq_p.ohlcv(s)
                if df is not None and len(df):
                    self.quotes[s] = Quote(float(df["close"].iloc[-1]), None, None,
                                           time.time(), "stooq(daily)")
        # sim fills any remaining gap (and everything when fully offline)
        self.sim.step(self.crypto_venues, self.arb_symbols)
        for s in self.crypto_symbols + self.slow_symbols:
            if s not in self.quotes or self.quotes[s].source.startswith("sim"):
                self.quotes[s] = self.sim.quote(s)
        for s in self.arb_symbols:
            for v in self.crypto_venues:
                k = (s, v)
                if k not in self.quotes or self.quotes[k].source.startswith("sim"):
                    self.quotes[k] = self.sim.venue_quote(s, v)
        self.simulated = not self.enabled_quotes_live()

    def enabled_quotes_live(self) -> bool:
        """True only when every enabled trading symbol has a non-synthetic quote."""
        for symbol in self.crypto_symbols + self.enabled_slow_symbols:
            quote = self.quotes.get(symbol)
            if quote is None or quote.source.startswith("sim"):
                return False
        for symbol in self.arb_symbols:
            for venue in self.crypto_venues:
                quote = self.quotes.get((symbol, venue))
                if quote is None or quote.source.startswith("sim"):
                    return False
        return True

    # ---------- access ----------
    def get(self, symbol: str) -> Quote | None:
        return self.quotes.get(symbol)

    def get_venue(self, symbol: str, venue: str) -> Quote | None:
        return self.quotes.get((symbol, venue))

    def get_ohlcv(self, symbol: str, timeframe: str = "1d", bars: int = 250) -> pd.DataFrame | None:
        mkt = market_of(symbol)
        if mkt == "crypto" and timeframe == "1h" and self.kraken_ws.refresh():
            df = self.kraken_ws.ohlcv(symbol, bars)
            if df is not None:
                return df
        if mkt == "crypto" and self.ccxt_p:
            df = self.ccxt_p.ohlcv(symbol, timeframe, bars)
            if df is not None:
                return df
        if mkt != "crypto":
            if self.yahoo_p:
                df = self.yahoo_p.ohlcv(symbol, timeframe, bars)
                if df is not None:
                    return df
            if self.stooq_p and timeframe == "1d":
                df = self.stooq_p.ohlcv(symbol, timeframe, bars)
                if df is not None:
                    return df
        return self.sim.ohlcv(symbol, timeframe, bars)
