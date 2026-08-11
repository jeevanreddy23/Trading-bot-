"""LIVE / practice FX executor via OANDA v20 REST API.

Env:  OANDA_API_TOKEN, OANDA_ACCOUNT_ID
Config execution.live.oanda_env: practice | live
OANDA practice accounts are free and are the recommended FX burn-in path.
"""
from __future__ import annotations

import os

import requests

from ..config import dig
from ..util import quote_ccy
from .base import Executor, Fill

HOSTS = {"practice": "https://api-fxpractice.oanda.com",
         "live": "https://api-fxtrade.oanda.com"}


def oanda_instrument(symbol: str) -> str:
    return f"{symbol[0:3]}_{symbol[3:6]}"          # AUDUSD=X -> AUD_USD


class OandaLiveExecutor(Executor):
    mode = "live:oanda"

    def __init__(self, cfg: dict):
        self.token = os.environ.get("OANDA_API_TOKEN")
        self.account = os.environ.get("OANDA_ACCOUNT_ID")
        if not self.token or not self.account:
            raise RuntimeError("missing OANDA_API_TOKEN / OANDA_ACCOUNT_ID in environment")
        env = dig(cfg, "execution.live.oanda_env", "practice")
        self.host = HOSTS.get(env, HOSTS["practice"])
        self.mode = f"live:oanda[{env}]"
        self.max_notional = float(dig(cfg, "execution.live.max_order_notional_aud", 200))

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def execute(self, sig, qty: float, ctx) -> Fill:
        if sig.market != "fx":
            return Fill(False, info="oanda executor only handles fx")
        inst = oanda_instrument(sig.symbol)
        ledger, feeds = ctx.ledger, ctx.feeds
        rates = ledger.rates_to_aud(feeds.quotes)
        ccy_rate = rates.get(quote_ccy(sig.symbol), rates["USD"])
        try:
            if sig.action == "close":
                key = ledger.pos_key(sig.symbol, sig.tag, sig.venue)
                pos = ledger.positions.get(key)
                if pos is None:
                    return Fill(False, info="no open position")
                side = "longUnits" if pos.qty > 0 else "shortUnits"
                r = requests.put(f"{self.host}/v3/accounts/{self.account}/positions/{inst}/close",
                                 headers=self._hdr(), json={side: "ALL"}, timeout=15)
                if r.status_code not in (200, 201):
                    return Fill(False, info=f"oanda close failed: {r.status_code} {r.text[:150]}")
                q = feeds.get(sig.symbol)
                px = (q.last if q else None) or sig.price or pos.avg_price
                pnl = ledger.close_position(key, px, 0.0, feeds.quotes, self.mode, sig.reason)
                return Fill(True, px, -pos.qty, 0.0, f"OANDA closed, P&L {pnl:+,.2f} AUD")

            q = feeds.get(sig.symbol)
            ref_px = (q.last if q else None) or sig.price
            notional_aud = qty * ref_px * ccy_rate
            if notional_aud > self.max_notional:
                qty = self.max_notional / (ref_px * ccy_rate)
            units = int(qty) if sig.action == "buy" else -int(qty)
            if units == 0:
                return Fill(False, info="sized below 1 unit")
            body = {"order": {"type": "MARKET", "instrument": inst,
                              "units": str(units), "timeInForce": "FOK",
                              "positionFill": "DEFAULT"}}
            r = requests.post(f"{self.host}/v3/accounts/{self.account}/orders",
                              headers=self._hdr(), json=body, timeout=15)
            if r.status_code not in (200, 201):
                return Fill(False, info=f"oanda order failed: {r.status_code} {r.text[:150]}")
            data = r.json()
            fill = data.get("orderFillTransaction", {})
            px = float(fill.get("price") or ref_px)
            ledger.open_position(sig, abs(units), px, 0.0, self.mode)
            return Fill(True, px, units, 0.0, f"OANDA {sig.action} {units} {inst} @ {px}")
        except Exception as e:
            return Fill(False, info=f"oanda error: {type(e).__name__}: {e}")
