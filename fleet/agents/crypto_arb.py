"""Cross-exchange crypto arbitrage scanner.

Scans venue order-book tops for the same pair, computes the NET edge after
both venues' taker fees and slippage allowance, and only fires when the net
edge clears a threshold. Publishes the best spread each cycle to the
dashboard's arb monitor — which most of the time shows exactly why naive
'arbitrage' loses money: gross gaps are usually smaller than the fees.

Live-trading caveat (documented in docs/GOING_LIVE.md): real two-legged arb
requires inventory pre-positioned on both venues. This agent's live mode is
therefore disabled by default; in paper mode both legs fill CFD-style.
"""
from __future__ import annotations

import time

from ..signals import Signal
from .base import Agent


class CryptoArbAgent(Agent):
    name = "crypto_arb"
    market = "crypto"
    interval = 15

    def evaluate(self, ctx) -> list:
        mcfg = ctx.cfg["markets"]["crypto"]
        fees = mcfg.get("taker_fees_bps", {})
        default_fee = fees.get("default", 20)
        thr = self.acfg.get("min_net_edge_bps", 5)
        slip_bps = 3
        max_leg = self.acfg.get("max_leg_notional_aud", 500)

        rows, signals = [], []
        for sym in mcfg.get("arb_symbols", []):
            venues = [v for v in mcfg.get("venues", []) if ctx.feeds.get_venue(sym, v)]
            best = None
            for vb in venues:                      # buy at vb's ask
                qb = ctx.feeds.get_venue(sym, vb)
                if not qb or not qb.ask:
                    continue
                for vs in venues:                  # sell at vs's bid
                    if vs == vb:
                        continue
                    qs = ctx.feeds.get_venue(sym, vs)
                    if not qs or not qs.bid:
                        continue
                    gross = (qs.bid - qb.ask) / qb.ask * 1e4
                    net = gross - fees.get(vb, default_fee) - fees.get(vs, default_fee) - 2 * slip_bps
                    if best is None or net > best["net_bps"]:
                        best = dict(symbol=sym, buy_venue=vb, sell_venue=vs,
                                    gross_bps=round(gross, 1), net_bps=round(net, 1),
                                    buy_px=qb.ask, sell_px=qs.bid)
            if best:
                rows.append(best)
                if best["net_bps"] >= thr:
                    pid = f"arb-{sym.split('/')[0]}-{int(time.time())}"
                    note = f"{best['buy_venue']}->{best['sell_venue']} net {best['net_bps']}bps"
                    conv = min(1.0, best["net_bps"] / 20)
                    signals.append(Signal(self.name, "crypto", sym, "buy", conv, note,
                                          best["buy_px"], venue=best["buy_venue"], tag=pid,
                                          max_notional_aud=max_leg))
                    signals.append(Signal(self.name, "crypto", sym, "sell", conv, note,
                                          best["sell_px"], venue=best["sell_venue"], tag=pid,
                                          max_notional_aud=max_leg))

        # unwind arb pairs after the window has had time to close
        for key, pos in list(ctx.ledger.positions.items()):
            if pos.agent == self.name and time.time() - pos.opened_ts > 6 * self.interval:
                signals.append(Signal(self.name, "crypto", pos.symbol, "close", 1.0,
                                      "arb unwind (window elapsed)", 0.0,
                                      venue=pos.venue, tag=pos.tag))

        ctx.state["arb"] = rows
        self.note = ("best net: " + ", ".join(f"{r['symbol']} {r['net_bps']:+.1f}bps" for r in rows)
                     ) if rows else "no venue quotes yet"
        return signals
