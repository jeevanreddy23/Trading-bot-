"""Runs the four research agents and emits only an ensemble-approved intention."""
from __future__ import annotations

from ..ensemble import DecisionEngine
from ..signals import Signal
from .base import Agent
from .momentum_agent import MomentumVoteAgent
from .regime_agent import RegimeAgent
from .reversal_agent import ReversalAgent
from .volatility_agent import VolatilityAgent


class CryptoEnsembleAgent(Agent):
    name = "crypto_ensemble"
    market = "crypto"
    interval = 300

    def __init__(self, cfg: dict, acfg: dict | None = None):
        super().__init__(cfg, acfg)
        self.models = [RegimeAgent(), MomentumVoteAgent(), ReversalAgent(),
                       VolatilityAgent(float(self.acfg.get("max_atr_pct", 4.0)))]
        self.engine = DecisionEngine(self.acfg)

    def evaluate(self, ctx) -> list:
        signals, notes = [], []
        decisions = ctx.state.setdefault("decisions", {})
        symbols = ctx.cfg["markets"]["crypto"].get("momentum_symbols", [])
        for symbol in symbols:
            frame = ctx.feeds.get_ohlcv(symbol, "1h", 240)
            quote = ctx.feeds.get(symbol)
            if frame is None or len(frame) < 60 or quote is None:
                notes.append(f"{symbol}:no-data")
                continue
            votes = [model.vote(frame) for model in self.models]
            decision = self.engine.decide(symbol, frame, quote, votes)
            decisions[symbol] = decision
            key = ctx.ledger.pos_key(symbol)
            have = key in ctx.ledger.positions
            if not have and decision["risk_gate"] == "PASS":
                signals.append(Signal(
                    self.name, "crypto", symbol, "buy", decision["probability"],
                    f"ensemble p={decision['probability']:.2f} EV={decision['expected_value_pct']:+.2f}%",
                    decision["entry"], stop=decision["stop"],
                ))
            elif have and decision["long_probability"] < float(self.acfg.get("exit_probability", 0.45)):
                signals.append(Signal(self.name, "crypto", symbol, "close", 1.0,
                                      "ensemble long probability deteriorated", decision["entry"]))
            notes.append(f"{symbol}:{decision['action']} p{decision['probability']:.2f} {decision['risk_gate']}")
        self.note = " | ".join(notes)
        return signals
