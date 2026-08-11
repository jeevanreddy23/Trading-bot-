"""Portfolio-level risk manager.

Every signal passes through evaluate() before execution. It can reject the
signal or return a sized quantity. Separate halt logic flattens the book and
stops the fleet on deep drawdown, and a KILL file gives a manual kill switch:
    touch state/KILL
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass

from .config import dig
from .util import quote_ccy


@dataclass
class RiskAssessment:
    passed: bool
    qty: float
    reason: str
    checks: dict

    def as_dict(self) -> dict:
        return asdict(self)


class RiskManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.r = cfg["risk"]
        self.kill_file = os.path.join(dig(cfg, "loop.state_dir", "state"), "KILL")

    def kill_switch(self) -> bool:
        return os.path.exists(self.kill_file)

    def assess(self, sig, ledger, quotes) -> RiskAssessment:
        """Return an auditable deterministic pre-order contract."""
        c = self.r
        if sig.action == "close":
            return RiskAssessment(True, 1.0, "close approved", {"risk_reducing": True})

        checks = {
            "not_halted": not ledger.halted,
            "kill_switch_clear": not self.kill_switch(),
            "daily_loss": True,
            "position_count": len(ledger.positions) < c["max_open_positions"],
            "position_unique": True,
            "shorts": sig.action != "sell" or sig.tag is not None or c["allow_shorts"].get(sig.market, False),
            "quote_fresh": False,
            "source_allowed": False,
            "spread": False,
            "gross_exposure": False,
            "market_exposure": False,
        }

        if ledger.halted:
            return RiskAssessment(False, 0.0, "halted (drawdown kill)", checks)
        if self.kill_switch():
            return RiskAssessment(False, 0.0, "KILL file present", checks)

        eq = ledger.equity(quotes)
        if eq <= 0:
            return RiskAssessment(False, 0.0, "no equity", checks)
        if ledger.daily_pnl(quotes) <= -eq * c["max_daily_loss_pct"] / 100:
            checks["daily_loss"] = False
            return RiskAssessment(False, 0.0, "daily loss limit hit", checks)
        if len(ledger.positions) >= c["max_open_positions"]:
            return RiskAssessment(False, 0.0, "max open positions", checks)

        key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
        if key in ledger.positions:
            checks["position_unique"] = False
            return RiskAssessment(False, 0.0, "position already open", checks)
        if sig.action == "sell" and sig.tag is None and not c["allow_shorts"].get(sig.market, False):
            return RiskAssessment(False, 0.0, f"shorts disabled for {sig.market}", checks)

        px = sig.price
        if not px or px <= 0:
            return RiskAssessment(False, 0.0, "no reference price", checks)

        quote = quotes.get((sig.symbol, sig.venue)) if sig.venue else quotes.get(sig.symbol)
        max_age = float(c.get("max_quote_age_seconds", 45))
        checks["quote_fresh"] = bool(quote and time.time() - float(quote.ts) <= max_age)
        checks["source_allowed"] = bool(quote and (
            self.cfg.get("mode") != "live" or not quote.source.startswith("sim")))
        if not checks["quote_fresh"] or not checks["source_allowed"]:
            return RiskAssessment(False, 0.0, "quote stale, missing, or synthetic", checks)
        spread_pct = ((quote.ask - quote.bid) / ((quote.ask + quote.bid) / 2) * 100
                      if quote.ask and quote.bid else 999.0)
        checks["spread"] = spread_pct <= float(c.get("max_spread_pct", 0.25))
        if not checks["spread"]:
            return RiskAssessment(False, 0.0, f"spread {spread_pct:.3f}% above limit", checks)

        rates = ledger.rates_to_aud(quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])

        notional = eq * c["max_position_pct_equity"] / 100 * max(0.1, min(1.0, sig.conviction))
        if sig.stop and sig.stop > 0 and abs(px - sig.stop) > 1e-12:
            risk_notional = (eq * c["risk_per_trade_pct"] / 100) * px / abs(px - sig.stop)
            notional = min(notional, risk_notional)
        if sig.max_notional_aud:
            notional = min(notional, sig.max_notional_aud)
        if notional <= 1:
            return RiskAssessment(False, 0.0, "sized to ~zero", checks)

        checks["gross_exposure"] = ledger.gross_exposure_aud(quotes) + notional <= eq * c["max_gross_leverage"]
        if not checks["gross_exposure"]:
            return RiskAssessment(False, 0.0, "gross leverage cap", checks)
        checks["market_exposure"] = (ledger.market_exposure_aud(sig.market, quotes) + notional
                                      <= eq * c["max_market_exposure_pct"] / 100)
        if not checks["market_exposure"]:
            return RiskAssessment(False, 0.0, f"{sig.market} exposure cap", checks)

        qty = notional / (px * ccy_rate)
        return RiskAssessment(True, qty, f"sized A${notional:,.0f}", checks)

    def evaluate(self, sig, ledger, quotes) -> tuple[float, str]:
        assessment = self.assess(sig, ledger, quotes)
        return assessment.qty, assessment.reason

    def check_halt(self, ledger, quotes) -> bool:
        eq = ledger.equity(quotes)
        peak = max((e for _, e in ledger.equity_series), default=eq)
        if peak > 0 and (peak - eq) / peak * 100 >= self.r["kill_drawdown_pct"]:
            ledger.halted = True
        return ledger.halted
