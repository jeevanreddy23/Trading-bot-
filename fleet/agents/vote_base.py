from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AgentVote:
    agent: str
    label: str
    confidence: float
    score: float
    reason: str

    def as_dict(self) -> dict:
        row = asdict(self)
        row["confidence"] = round(max(0.0, min(1.0, self.confidence)), 3)
        row["score"] = round(max(-1.0, min(1.0, self.score)), 3)
        return row
