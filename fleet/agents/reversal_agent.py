from __future__ import annotations

from ..indicators import zscore
from .vote_base import AgentVote


class ReversalAgent:
    name = "reversal"

    def vote(self, frame) -> AgentVote:
        z = float(zscore(frame["close"], 20).iloc[-1])
        score = max(-1.0, min(1.0, -z / 2.5))
        confidence = min(0.95, 0.45 + abs(z) * 0.18)
        label = "LONG" if score > 0.4 else "SHORT" if score < -0.4 else "NEUTRAL"
        return AgentVote(self.name, label, confidence, score, f"20-bar z-score {z:+.2f}")
