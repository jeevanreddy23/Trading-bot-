from __future__ import annotations

from ..indicators import atr, ema
from .vote_base import AgentVote


class RegimeAgent:
    name = "regime"

    def vote(self, frame) -> AgentVote:
        close = frame["close"]
        fast, slow = ema(close, 20), ema(close, 50)
        px = float(close.iloc[-1])
        atr_pct = float(atr(frame, 14).iloc[-1]) / px if px else 0
        separation = (float(fast.iloc[-1]) - float(slow.iloc[-1])) / max(px, 1e-12)
        slope = (float(slow.iloc[-1]) - float(slow.iloc[-6])) / max(px, 1e-12)
        strength = min(1.0, abs(separation) / max(atr_pct, 1e-6) + abs(slope) * 20)
        direction = 1.0 if separation > 0 and slope >= 0 else -1.0 if separation < 0 and slope <= 0 else 0.0
        label = "TRENDING UP" if direction > 0 else "TRENDING DOWN" if direction < 0 else "RANGING"
        return AgentVote(self.name, label, 0.5 + 0.5 * strength, direction * strength,
                         f"EMA20/50 separation {separation * 100:+.2f}%")
