#!/usr/bin/env python3
"""Deterministic engine checks — no network, no randomness in the assertions.

Run:  python tests/test_engine.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet.config import load_config
from fleet.coordinator import Coordinator
from fleet.signals import Signal

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))
    print(f"[{PASS if cond else FAIL}] {name} {detail}")


def main():
    cfg = load_config()
    cfg["loop"]["state_dir"] = "state_test"
    co = Coordinator(cfg, force_sim=True, reset=True, quiet=True)
    co.feeds.refresh()
    L, F = co.ledger, co.feeds
    eq0 = L.equity(F.quotes)
    check("starting equity", abs(eq0 - cfg["starting_equity"]) < 1e-6, f"= {eq0}")

    # --- 1. paper open -> +1% move -> close: P&L ≈ notional% - fees/slippage ---
    sym = "BTC/USDT"
    px = F.get(sym).last
    sig = Signal("test", "crypto", sym, "buy", 1.0, "test buy", px)
    qty, reason = co.risk.evaluate(sig, L, F.quotes)
    check("risk sizes buy", qty > 0, reason)
    co._exec(sig, qty)
    key = L.pos_key(sym)
    check("position opened", key in L.positions)
    entry = L.positions[key].avg_price

    F.sim.prices[sym] *= 1.01                      # +1% move
    F.refresh()
    rates = L.rates_to_aud(F.quotes)
    upnl = L.unrealized_aud(L.positions[key], F.quotes, rates)
    check("unrealized P&L positive after +1%", upnl > 0, f"{upnl:+.2f} AUD")

    co._exec(Signal("test", "crypto", sym, "close", 1.0, "test close", 0.0), 0.0)
    check("position closed", key not in L.positions)
    eq1 = L.equity(F.quotes)
    expected = qty * entry * rates["USD"] * 0.01   # rough: 1% of notional
    realized = eq1 - eq0
    check("realized ≈ 1% of notional minus costs",
          0.3 * expected < realized < 1.1 * expected,
          f"realized {realized:+.2f} vs gross-move {expected:+.2f} AUD")

    # --- 2. stop-loss enforcement ---
    px = F.get("GC=F").last
    stop_sig = Signal("test", "commodities", "GC=F", "buy", 1.0, "test stop", px, stop=px * 0.995)
    qty, reason = co.risk.evaluate(stop_sig, L, F.quotes)
    check("risk sizes stop trade", qty > 0, reason)
    co._exec(stop_sig, qty)
    F.sim.prices["GC=F"] *= 0.99                   # crash through the stop
    F.refresh()
    stops = co.stop_checks()
    check("stop breach detected", len(stops) == 1, f"{len(stops)} stop signals")
    co.process_signals(stops)
    check("stopped position closed", L.pos_key("GC=F") not in L.positions)

    # --- 3. arb pair atomicity + forced dislocation executes both legs ---
    F.sim.dislocation[("ETH/USDT", "okx")] = (-120.0, 4)     # okx cheap
    F.sim.dislocation[("ETH/USDT", "bybit")] = (120.0, 4)    # bybit rich
    # refresh venue quotes only (skip step() so the dislocation isn't decayed)
    for v in F.crypto_venues:
        F.quotes[("ETH/USDT", v)] = F.sim.venue_quote("ETH/USDT", v)
    arb = next(a for a in co.agents if a.name == "crypto_arb")
    sigs = arb.run(co.ctx)
    pair = [s for s in sigs if s.tag and s.tag.startswith("arb-ETH")]
    check("arb window detected on forced 240bps dislocation", len(pair) == 2,
          f"{len(pair)} legs, monitor: {co.ctx.state['arb']}")
    co.process_signals(sigs)
    legs_open = [k for k, p in L.positions.items() if p.agent == "crypto_arb"]
    check("both arb legs opened atomically", len(legs_open) == 2, str(legs_open))
    for k in list(legs_open):
        p = L.positions[k]
        co._exec(Signal("crypto_arb", "crypto", p.symbol, "close", 1.0, "test unwind",
                        0.0, venue=p.venue, tag=p.tag), 0.0)
    check("arb legs unwound", not any(p.agent == "crypto_arb" for p in L.positions.values()))

    # --- 4. shorts blocked for stocks, allowed for fx ---
    q, r = co.risk.evaluate(Signal("t", "stocks", "AAPL", "sell", 1.0, "", 100.0), L, F.quotes)
    check("stock short rejected", q == 0, r)
    q, r = co.risk.evaluate(Signal("t", "fx", "EURUSD=X", "sell", 1.0, "",
                                   F.get("EURUSD=X").last), L, F.quotes)
    check("fx short allowed", q > 0, r)

    # --- 5. per-order + leverage caps ---
    q, _ = co.risk.evaluate(Signal("t", "crypto", "BTC/USDT", "buy", 1.0, "",
                                   F.get("BTC/USDT").last, max_notional_aud=50), L, F.quotes)
    rates = L.rates_to_aud(F.quotes)
    notional = q * F.get("BTC/USDT").last * rates["USD"]
    check("signal notional cap respected", notional <= 50.5, f"A${notional:.2f}")

    # --- 6. daily-loss gate ---
    L.day_start_equity = L.equity(F.quotes) + 1000   # pretend we're down $1000 today
    q, r = co.risk.evaluate(Signal("t", "crypto", "BTC/USDT", "buy", 1.0, "",
                                   F.get("BTC/USDT").last), L, F.quotes)
    check("daily loss limit blocks new entries", q == 0, r)
    L.day_start_equity = L.equity(F.quotes)

    # --- 7. kill file halts and flattens ---
    open(co.risk.kill_file, "w").close()
    co._exec(Signal("test", "crypto", "BTC/USDT", "buy", 1.0, "pre-kill", F.get("BTC/USDT").last), 0.01)
    co.cycle()
    check("KILL file flattens book", len(L.positions) == 0,
          f"{len(L.positions)} positions remain")
    os.remove(co.risk.kill_file)

    n_fail = sum(1 for s, *_ in results if s == FAIL)
    print(f"\n{len(results) - n_fail}/{len(results)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
