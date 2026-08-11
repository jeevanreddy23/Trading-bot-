"""ASX + US equities on daily bars.

Two long-only entries:
  momentum   — SMA20 crosses above SMA50 in an uptrend, RSI sanity band
  mean-rev   — RSI(2) < 10 dip while above SMA200 (classic pullback-in-uptrend)
"""
from __future__ import annotations

from ..indicators import atr, rsi, sma
from ..signals import Signal
from .base import Agent


class StocksAgent(Agent):
    name = "stocks"
    market = "stocks"
    interval = 600

    def evaluate(self, ctx) -> list:
        scfg = ctx.cfg["markets"]["stocks"]
        syms = list(scfg.get("asx", [])) + list(scfg.get("us", []))
        out, notes = [], []
        for sym in syms:
            df = ctx.feeds.get_ohlcv(sym, "1d", 260)
            if df is None or len(df) < 210:
                notes.append(f"{sym}:nodata")
                continue
            c = df["close"]
            s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
            r14, r2 = rsi(c, 14), rsi(c, 2)
            a = float(atr(df, 14).iloc[-1])
            px = float(c.iloc[-1])

            mom_key = ctx.ledger.pos_key(sym, "mom")
            mr_key = ctx.ledger.pos_key(sym, "mr")

            if mom_key in ctx.ledger.positions and px < s50.iloc[-1]:
                out.append(Signal(self.name, "stocks", sym, "close", 1.0,
                                  "closed below SMA50", px, tag="mom"))
            if mr_key in ctx.ledger.positions and r2.iloc[-1] > 70:
                out.append(Signal(self.name, "stocks", sym, "close", 1.0,
                                  "RSI(2) recovered", px, tag="mr"))

            if mom_key not in ctx.ledger.positions:
                recent_cross = bool((s20.iloc[-4:-1] <= s50.iloc[-4:-1]).any()) and s20.iloc[-1] > s50.iloc[-1]
                if px > s50.iloc[-1] and recent_cross and 45 <= r14.iloc[-1] <= 70:
                    out.append(Signal(self.name, "stocks", sym, "buy", 0.55,
                                      "SMA20>SMA50 momentum", px, stop=px - 2.5 * a, tag="mom"))
            if mr_key not in ctx.ledger.positions:
                if r2.iloc[-1] < 10 and px > s200.iloc[-1]:
                    out.append(Signal(self.name, "stocks", sym, "buy", 0.5,
                                      "RSI(2) dip in uptrend", px, stop=px - 2 * a, tag="mr"))
            notes.append(f"{sym}:{'>' if px > s50.iloc[-1] else '<'}50d")
        self.note = " ".join(notes[:12])
        return out
