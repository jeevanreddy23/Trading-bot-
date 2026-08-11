"""Crypto momentum on 1-hour candles: EMA 12/26 cross with RSI filter, ATR stop."""
from __future__ import annotations

from ..indicators import atr, ema, rsi
from ..signals import Signal
from .base import Agent


class CryptoMomentumAgent(Agent):
    name = "crypto_momentum"
    market = "crypto"
    interval = 300

    def evaluate(self, ctx) -> list:
        out, notes = [], []
        for sym in ctx.cfg["markets"]["crypto"].get("momentum_symbols", []):
            df = ctx.feeds.get_ohlcv(sym, "1h", 200)
            if df is None or len(df) < 60:
                notes.append(f"{sym}:nodata")
                continue
            if getattr(ctx, "live", False) and df.attrs.get("source") == "sim":
                notes.append(f"{sym}:synthetic-history-refused")
                continue
            e12, e26 = ema(df["close"], 12), ema(df["close"], 26)
            r = rsi(df["close"], 14)
            a = float(atr(df, 14).iloc[-1])
            px = float(df["close"].iloc[-1])
            key = ctx.ledger.pos_key(sym)
            have = key in ctx.ledger.positions
            cross_up = e12.iloc[-1] > e26.iloc[-1] and e12.iloc[-2] <= e26.iloc[-2]
            trend_dn = e12.iloc[-1] < e26.iloc[-1]

            if not have and cross_up and r.iloc[-1] < 72:
                out.append(Signal(self.name, "crypto", sym, "buy", 0.6,
                                  "EMA12/26 cross up (1h)", px, stop=px - 2 * a))
            elif have and (trend_dn or r.iloc[-1] > 80):
                out.append(Signal(self.name, "crypto", sym, "close", 1.0,
                                  "EMA cross down / RSI overheated", px))
            notes.append(f"{sym}:{'up' if not trend_dn else 'dn'} rsi{r.iloc[-1]:.0f}")
        self.note = " ".join(notes)
        return out
