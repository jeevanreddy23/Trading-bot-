"""Commodities trend-following on daily bars: 20-day Donchian breakout,
10-day channel exit, ATR stops. Shorts allowed (configurable)."""
from __future__ import annotations

from ..indicators import atr
from ..signals import Signal
from .base import Agent


class CommoditiesAgent(Agent):
    name = "commodities"
    market = "commodities"
    interval = 600

    def evaluate(self, ctx) -> list:
        out, notes = [], []
        allow_short = ctx.cfg["risk"]["allow_shorts"].get("commodities", False)
        for sym in ctx.cfg["markets"]["commodities"].get("symbols", []):
            df = ctx.feeds.get_ohlcv(sym, "1d", 120)
            if df is None or len(df) < 60:
                notes.append(f"{sym}:nodata")
                continue
            c = df["close"]
            hi20 = float(c.rolling(20).max().shift(1).iloc[-1])
            lo20 = float(c.rolling(20).min().shift(1).iloc[-1])
            hi10 = float(c.rolling(10).max().shift(1).iloc[-1])
            lo10 = float(c.rolling(10).min().shift(1).iloc[-1])
            a = float(atr(df, 14).iloc[-1])
            px = float(df["close"].iloc[-1])

            key = ctx.ledger.pos_key(sym)
            pos = ctx.ledger.positions.get(key)
            if pos is not None:
                if pos.qty > 0 and px <= lo10:
                    out.append(Signal(self.name, "commodities", sym, "close", 1.0,
                                      "10d channel exit (long)", px))
                elif pos.qty < 0 and px >= hi10:
                    out.append(Signal(self.name, "commodities", sym, "close", 1.0,
                                      "10d channel exit (short)", px))
            else:
                if px >= hi20:
                    out.append(Signal(self.name, "commodities", sym, "buy", 0.55,
                                      "20d breakout", px, stop=px - 2 * a))
                elif allow_short and px <= lo20:
                    out.append(Signal(self.name, "commodities", sym, "sell", 0.55,
                                      "20d breakdown", px, stop=px + 2 * a))
            notes.append(f"{sym}:{'^' if px >= hi20 else 'v' if px <= lo20 else '-'}")
        self.note = " ".join(notes)
        return out
