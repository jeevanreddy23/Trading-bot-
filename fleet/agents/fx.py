"""FX mean reversion on 1-hour bars: z-score of price vs 20-period mean.
Enter beyond ±2σ, exit inside ±0.5σ. Long and short."""
from __future__ import annotations

from ..indicators import atr, zscore
from ..signals import Signal
from .base import Agent


class FXAgent(Agent):
    name = "fx"
    market = "fx"
    interval = 300

    def evaluate(self, ctx) -> list:
        out, notes = [], []
        allow_short = ctx.cfg["risk"]["allow_shorts"].get("fx", True)
        for sym in ctx.cfg["markets"]["fx"].get("symbols", []):
            df = ctx.feeds.get_ohlcv(sym, "1h", 200)
            if df is None or len(df) < 40:
                notes.append(f"{sym}:nodata")
                continue
            z = float(zscore(df["close"], 20).iloc[-1])
            a = float(atr(df, 14).iloc[-1])
            px = float(df["close"].iloc[-1])

            key = ctx.ledger.pos_key(sym)
            pos = ctx.ledger.positions.get(key)
            if pos is not None:
                if abs(z) < 0.5:
                    out.append(Signal(self.name, "fx", sym, "close", 1.0,
                                      f"reverted (z={z:+.2f})", px))
            else:
                if z < -2:
                    out.append(Signal(self.name, "fx", sym, "buy", 0.5,
                                      f"oversold z={z:+.2f}", px, stop=px - 1.5 * a))
                elif z > 2 and allow_short:
                    out.append(Signal(self.name, "fx", sym, "sell", 0.5,
                                      f"overbought z={z:+.2f}", px, stop=px + 1.5 * a))
            notes.append(f"{sym}:z{z:+.1f}")
        self.note = " ".join(notes)
        return out
