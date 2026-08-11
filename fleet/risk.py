"""Portfolio-level risk manager.

Every signal passes through evaluate() before execution. It can reject the
signal or return a sized quantity. Separate halt logic flattens the book and
stops the fleet on deep drawdown, and a KILL file gives a manual kill switch:
    touch state/KILL
"""
from __future__ import annotations

import os

from .config import dig
from .util import quote_ccy


class RiskManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.r = cfg["risk"]
        self.kill_file = os.path.join(dig(cfg, "loop.state_dir", "state"), "KILL")

    def kill_switch(self) -> bool:
        return os.path.exists(self.kill_file)

    def evaluate(self, sig, ledger, quotes) -> tuple[float, str]:
        """Return (qty, reason). qty == 0 means rejected."""
        c = self.r
        if sig.action == "close":
            return (1.0, "close approved")          # risk reduction is always allowed

        if ledger.halted:
            return (0.0, "halted (drawdown kill)")
        if self.kill_switch():
            return (0.0, "KILL file present")

        eq = ledger.equity(quotes)
        if eq <= 0:
            return (0.0, "no equity")
        if ledger.daily_pnl(quotes) <= -eq * c["max_daily_loss_pct"] / 100:
            return (0.0, "daily loss limit hit")
        if len(ledger.positions) >= c["max_open_positions"]:
            return (0.0, "max open positions")

        key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
        if key in ledger.positions:
            return (0.0, "position already open")
        if sig.action == "sell" and sig.tag is None and not c["allow_shorts"].get(sig.market, False):
            return (0.0, f"shorts disabled for {sig.market}")

        px = sig.price
        if not px or px <= 0:
            return (0.0, "no reference price")

        rates = ledger.rates_to_aud(quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])

        notional = eq * c["max_position_pct_equity"] / 100 * max(0.1, min(1.0, sig.conviction))
        if sig.stop and sig.stop > 0 and abs(px - sig.stop) > 1e-12:
            risk_notional = (eq * c["risk_per_trade_pct"] / 100) * px / abs(px - sig.stop)
            notional = min(notional, risk_notional)
        if sig.max_notional_aud:
            notional = min(notional, sig.max_notional_aud)
        if notional <= 1:
            return (0.0, "sized to ~zero")

        if ledger.gross_exposure_aud(quotes) + notional > eq * c["max_gross_leverage"]:
            return (0.0, "gross leverage cap")
        if ledger.market_exposure_aud(sig.market, quotes) + notional > eq * c["max_market_exposure_pct"] / 100:
            return (0.0, f"{sig.market} exposure cap")

        qty = notional / (px * ccy_rate)
        return (qty, f"sized A${notional:,.0f}")

    def check_halt(self, ledger, quotes) -> bool:
        eq = ledger.equity(quotes)
        peak = max((e for _, e in ledger.equity_series), default=eq)
        if peak > 0 and (peak - eq) / peak * 100 >= self.r["kill_drawdown_pct"]:
            ledger.halted = True
        return ledger.halted
