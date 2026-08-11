"""Paper executor: fills at the live quote with configurable slippage + fees.
This is the default executor and the only one that runs without API keys."""
from __future__ import annotations

from ..util import market_open, quote_ccy
from .base import Executor, Fill


class PaperExecutor(Executor):
    mode = "paper"

    def __init__(self, cfg: dict):
        pcfg = cfg["execution"]["paper"]
        self.slip = pcfg.get("slippage_bps", {})
        self.fees = pcfg.get("fee_bps", {})

    def execute(self, sig, qty: float, ctx) -> Fill:
        ledger, feeds = ctx.ledger, ctx.feeds
        q = feeds.get_venue(sig.symbol, sig.venue) if sig.venue else feeds.get(sig.symbol)
        if q is None or not q.last:
            return Fill(False, info="no quote")
        slip = self.slip.get(sig.market, 5) / 1e4
        fee_rate = self.fees.get(sig.market, 10) / 1e4
        rates = ledger.rates_to_aud(feeds.quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])
        oob = "" if market_open(sig.symbol) else " [after-hours mark]"

        if sig.action == "close":
            key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
            pos = ledger.positions.get(key)
            if pos is None:
                return Fill(False, info="no open position")
            if pos.qty > 0:
                px = (q.bid or q.last) * (1 - slip)
            else:
                px = (q.ask or q.last) * (1 + slip)
            fee = abs(pos.qty) * px * ccy_rate * fee_rate
            pnl = ledger.close_position(key, px, fee, feeds.quotes, self.mode, sig.reason)
            return Fill(True, px, -pos.qty, fee, f"closed, P&L {pnl:+,.2f} AUD{oob}")

        if sig.action == "buy":
            px = (q.ask or q.last) * (1 + slip)
        else:
            px = (q.bid or q.last) * (1 - slip)
        fee = qty * px * ccy_rate * fee_rate
        ledger.open_position(sig, qty, px, fee, self.mode)
        return Fill(True, px, qty, fee,
                    f"opened {qty:.6g} @ {px:,.6g} ({sig.reason}){oob}")
