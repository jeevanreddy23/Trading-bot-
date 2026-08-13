from __future__ import annotations

from ..indicators import atr
from .vote_base import AgentVote


class VolatilityAgent:
    name = "volatility"

    def __init__(self, max_atr_pct: float = 4.0):
        self.max_atr_pct = max_atr_pct

    def vote(self, frame) -> AgentVote:
        px = float(frame["close"].iloc[-1])
        atr_pct = float(atr(frame, 14).iloc[-1]) / max(px, 1e-12) * 100
        acceptable = atr_pct <= self.max_atr_pct
        confidence = max(0.05, min(0.99, 1 - atr_pct / max(self.max_atr_pct * 1.5, 0.01)))
        return AgentVote(self.name, "ACCEPTABLE" if acceptable else "HIGH", confidence,
                         0.0 if acceptable else -1.0, f"ATR14 {atr_pct:.2f}%")
