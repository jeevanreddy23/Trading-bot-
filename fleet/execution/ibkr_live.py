"""LIVE stocks/futures executor via Interactive Brokers (ib_insync).

IBKR is the practical API broker for ASX stocks + commodity futures for
Australian residents. This executor requires TWS or IB Gateway running on
the SAME machine as the fleet (paper: port 7497, live: 7496) and:
    pip install ib_insync
It will simply fail to construct when unavailable — the coordinator then
routes those markets to paper with a warning.
"""
from __future__ import annotations

from ..config import dig
from ..util import quote_ccy
from .base import Executor, Fill


def _contract(symbol: str):
    from ib_insync import Future, Stock
    if symbol.endswith(".AX"):
        return Stock(symbol[:-3], "ASX", "AUD")
    if symbol.endswith("=F"):
        # front-month continuous mapping left to the user's contract config;
        # GC -> COMEX gold etc. This is a minimal example for US futures roots.
        roots = {"GC=F": ("GC", "COMEX"), "SI=F": ("SI", "COMEX"), "HG=F": ("HG", "COMEX"),
                 "CL=F": ("CL", "NYMEX"), "NG=F": ("NG", "NYMEX"), "ZW=F": ("ZW", "CBOT")}
        root, exch = roots.get(symbol, (symbol[:-2], "SMART"))
        return Future(root, exchange=exch, currency="USD")
    return Stock(symbol, "SMART", "USD")


class IbkrLiveExecutor(Executor):
    mode = "live:ibkr"

    def __init__(self, cfg: dict):
        from ib_insync import IB  # raises ImportError if not installed
        self.IB = IB
        self.ib = IB()
        port = int(dig(cfg, "execution.live.ibkr_port", 7497))
        self.ib.connect("127.0.0.1", port, clientId=17)
        self.max_notional = float(dig(cfg, "execution.live.max_order_notional_aud", 200))

    def execute(self, sig, qty: float, ctx) -> Fill:
        from ib_insync import MarketOrder
        ledger, feeds = ctx.ledger, ctx.feeds
        rates = ledger.rates_to_aud(feeds.quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])
        try:
            contract = _contract(sig.symbol)
            self.ib.qualifyContracts(contract)
            if sig.action == "close":
                key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
                pos = ledger.positions.get(key)
                if pos is None:
                    return Fill(False, info="no open position")
                action = "SELL" if pos.qty > 0 else "BUY"
                trade = self.ib.placeOrder(contract, MarketOrder(action, abs(round(pos.qty))))
                self.ib.sleep(2)
                px = trade.orderStatus.avgFillPrice or pos.avg_price
                pnl = ledger.close_position(key, px, 0.0, feeds.quotes, self.mode, sig.reason)
                return Fill(True, px, -pos.qty, 0.0, f"IBKR closed, P&L {pnl:+,.2f} AUD")

            q = feeds.get(sig.symbol)
            ref_px = (q.last if q else None) or sig.price
            if qty * ref_px * ccy_rate > self.max_notional:
                qty = self.max_notional / (ref_px * ccy_rate)
            amount = max(1, int(qty))
            action = "BUY" if sig.action == "buy" else "SELL"
            trade = self.ib.placeOrder(contract, MarketOrder(action, amount))
            self.ib.sleep(2)
            px = trade.orderStatus.avgFillPrice or ref_px
            ledger.open_position(sig, amount, px, 0.0, self.mode)
            return Fill(True, px, amount, 0.0, f"IBKR {action} {amount} @ {px}")
        except Exception as e:
            return Fill(False, info=f"ibkr error: {type(e).__name__}: {e}")
