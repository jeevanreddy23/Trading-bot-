from __future__ import annotations

from ..indicators import ema, rsi
from .vote_base import AgentVote


class MomentumVoteAgent:
    name = "momentum"

    def vote(self, frame) -> AgentVote:
        close = frame["close"]
        e12, e26 = ema(close, 12), ema(close, 26)
        value = float(rsi(close, 14).iloc[-1])
        spread = (float(e12.iloc[-1]) - float(e26.iloc[-1])) / max(float(close.iloc[-1]), 1e-12)
        raw = max(-1.0, min(1.0, spread * 120))
        if value > 78:
            raw = min(raw, 0.15)
        elif value < 22:
            raw = max(raw, -0.15)
        confidence = min(0.95, 0.5 + abs(raw) * 0.45)
        label = "LONG" if raw > 0.12 else "SHORT" if raw < -0.12 else "NEUTRAL"
        return AgentVote(self.name, label, confidence, raw, f"EMA12/26 {spread * 100:+.2f}%, RSI {value:.1f}")
