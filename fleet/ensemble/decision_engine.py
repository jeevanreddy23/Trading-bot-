"""Explainable probability/EV aggregation. It never places orders."""
from __future__ import annotations

from ..indicators import atr


class DecisionEngine:
    WEIGHTS = {"regime": 0.30, "momentum": 0.45, "reversal": 0.25}

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def decide(self, symbol: str, frame, quote, votes: list) -> dict:
        directional = sum(self.WEIGHTS.get(v.agent, 0) * v.score * v.confidence for v in votes)
        probability_long = max(0.01, min(0.99, 0.5 + directional / 2))
        probability_short = 1 - probability_long
        action = "LONG" if probability_long >= 0.5 else "SHORT"
        probability = max(probability_long, probability_short)
        px = float(frame["close"].iloc[-1])
        atr_value = float(atr(frame, 14).iloc[-1])
        spread_pct = ((quote.ask - quote.bid) / ((quote.ask + quote.bid) / 2) * 100
                      if quote and quote.ask and quote.bid else 999.0)
        fees_pct = float(self.cfg.get("round_trip_fees_pct", 0.8))
        gross_edge_pct = abs(directional) * (atr_value / max(px, 1e-12) * 100)
        expected_value_pct = gross_edge_pct - fees_pct - spread_pct
        volatility = next(v for v in votes if v.agent == "volatility")
        quote_age = max(0.0, __import__("time").time() - float(getattr(quote, "ts", 0)))
        source_live = bool(quote and not quote.source.startswith("sim"))
        max_spread = float(self.cfg.get("max_spread_pct", 0.25))
        min_probability = float(self.cfg.get("min_probability", 0.62))
        min_ev = float(self.cfg.get("min_ev_pct", 0.05))
        max_age = float(self.cfg.get("max_quote_age_seconds", 45))
        checks = {
            "source_live": source_live,
            "quote_fresh": quote_age <= max_age,
            "spread": spread_pct <= max_spread,
            "volatility": volatility.label == "ACCEPTABLE",
            "probability": probability >= min_probability,
            "expected_value": expected_value_pct >= min_ev,
        }
        risk_gate = all(checks.values()) and action == "LONG"
        stop = px - 1.5 * atr_value
        target = px + 2.5 * atr_value
        return {
            "symbol": symbol, "timeframe": "1h", "source": frame.attrs.get("source", "unknown"),
            "votes": [v.as_dict() for v in votes], "action": action,
            "long_probability": round(probability_long, 3), "probability": round(probability, 3),
            "expected_value_pct": round(expected_value_pct, 3), "spread_pct": round(spread_pct, 4),
            "entry": round(px, 8), "stop": round(stop, 8), "target": round(target, 8),
            "risk_gate": "PASS" if risk_gate else "FAIL", "checks": checks,
            "deterministic_risk": {"status": "PENDING", "reason": "awaiting signal"},
            "candles": [
                {"time": int(ts.timestamp()), "open": float(row.open), "high": float(row.high),
                 "low": float(row.low), "close": float(row.close)}
                for ts, row in frame.tail(150).iterrows()
            ],
        }
