"""LIVE crypto executor via CCXT. Places REAL market orders.

Requirements (all must hold, or it refuses):
  - config mode: live  AND  run.py --live
  - env LIVE_TRADING_ACK=I_UNDERSTAND_THE_RISKS
  - env <VENUE>_API_KEY / <VENUE>_API_SECRET  (e.g. KRAKEN_API_KEY)
    -> create keys WITHOUT withdrawal permission. Ever.
  - order notional <= execution.live.max_order_notional_aud

Live arb note: the sell leg of an arb pair requires inventory on that venue.
This executor rejects short/sell openings on spot venues.
"""
from __future__ import annotations

import os

from ..config import dig
from ..util import quote_ccy
from .base import Executor, Fill


class CcxtLiveExecutor(Executor):
    mode = "live:ccxt"

    def __init__(self, cfg: dict):
        import ccxt
        self.cfg = cfg
        venue = dig(cfg, "execution.live.crypto_venue", "kraken")
        self.venue = venue
        key = os.environ.get(f"{venue.upper()}_API_KEY")
        sec = os.environ.get(f"{venue.upper()}_API_SECRET")
        if not key or not sec:
            raise RuntimeError(f"missing {venue.upper()}_API_KEY / _API_SECRET in environment")
        self.ex = getattr(ccxt, venue)({
            "apiKey": key, "secret": sec, "enableRateLimit": True, "timeout": 15000,
        })
        self.ex.load_markets()
        self.max_notional = float(dig(cfg, "execution.live.max_order_notional_aud", 200))

    def execute(self, sig, qty: float, ctx) -> Fill:
        if sig.market != "crypto":
            return Fill(False, info="ccxt live executor only handles crypto")
        if sig.venue and sig.venue != self.venue:
            return Fill(False, info=f"signal venue {sig.venue} is not live venue {self.venue}")
        if sig.tag and sig.tag.startswith("arb-"):
            return Fill(False, info="live cross-venue arbitrage is disabled")
        if sig.symbol not in self.ex.markets:
            return Fill(False, info=f"{sig.symbol} not on {self.venue}")

        ledger, feeds = ctx.ledger, ctx.feeds
        rates = ledger.rates_to_aud(feeds.quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])

        try:
            if sig.action == "close":
                key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
                pos = ledger.positions.get(key)
                if pos is None:
                    return Fill(False, info="no open position")
                if pos.qty < 0:
                    return Fill(False, info="live short close unsupported on spot")
                amount = float(self.ex.amount_to_precision(sig.symbol, abs(pos.qty)))
                order = self.ex.create_order(sig.symbol, "market", "sell", amount)
                px = float(order.get("average") or order.get("price") or 0) or pos.avg_price
                fee = abs(amount) * px * ccy_rate * 0.0026
                pnl = ledger.close_position(key, px, fee, feeds.quotes, self.mode, sig.reason)
                ledger.persist()
                return Fill(True, px, -amount, fee, f"LIVE closed, P&L {pnl:+,.2f} AUD")

            if sig.action == "sell":
                return Fill(False, info="live spot cannot open shorts (arb sell leg refused)")

            q = feeds.get(sig.symbol)
            if q is None or q.source.startswith("sim"):
                return Fill(False, info="live entry refused: quote is missing or synthetic")
            ref_px = (q.ask or q.last) if q else sig.price
            notional_aud = qty * ref_px * ccy_rate
            if notional_aud > self.max_notional:
                qty = self.max_notional / (ref_px * ccy_rate)
                notional_aud = self.max_notional
            bal = self.ex.fetch_balance()
            quote = sig.symbol.split("/")[1]
            free = float(bal.get(quote, {}).get("free") or 0)
            if free < qty * ref_px * 1.01:
                return Fill(False, info=f"insufficient {quote} balance ({free:.2f})")
            amount = float(self.ex.amount_to_precision(sig.symbol, qty))
            if amount <= 0:
                return Fill(False, info="order amount rounded to zero")
            order = self.ex.create_order(sig.symbol, "market", "buy", amount)
            px = float(order.get("average") or order.get("price") or 0) or ref_px
            fee = amount * px * ccy_rate * 0.0026
            ledger.open_position(sig, amount, px, fee, self.mode)
            ledger.persist()
            return Fill(True, px, amount, fee, f"LIVE bought {amount} @ {px:,.2f}")
        except Exception as e:
            return Fill(False, info=f"live order failed: {type(e).__name__}: {e}")
