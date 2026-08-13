#!/usr/bin/env python3
"""Aussie Agent Fleet — multi-market trading agent fleet.

Examples:
  python run.py                          # paper trade, real data, forever
  python run.py --cycles 20              # paper trade, 20 cycles, then exit
  python run.py --sim --cycles 12        # offline synthetic demo
  python run.py --reset                  # start the paper book fresh
  python run.py --live                   # LIVE (requires config mode: live,
                                         #  API keys + LIVE_TRADING_ACK env)
Kill switch at any time:  touch state/KILL
"""
from __future__ import annotations

import argparse

from fleet.config import load_config
from fleet.coordinator import Coordinator
from fleet.dashboard import render_dashboard
from monitor.local_snapshot import write_local_snapshot


def main():
    ap = argparse.ArgumentParser(description="Aussie Agent Fleet")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--cycles", type=int, default=0, help="run N cycles then exit (0 = forever)")
    ap.add_argument("--interval", type=float, default=None, help="seconds per cycle")
    ap.add_argument("--sim", action="store_true", help="force synthetic data (offline demo)")
    ap.add_argument("--reset", action="store_true", help="reset paper ledger and logs")
    ap.add_argument("--live", action="store_true", help="attempt live trading (interlocked)")
    ap.add_argument("--dash-every", type=int, default=4, help="render dashboard every N cycles")
    args = ap.parse_args()

    cfg = load_config(args.config)
    interval = args.interval or cfg.get("loop", {}).get("interval_seconds", 15)
    cycles = args.cycles if args.cycles > 0 else 10 ** 9

    co = Coordinator(cfg, force_sim=args.sim, live=args.live, reset=args.reset)
    if args.live and not co.live:
        raise SystemExit(
            "[fleet] LIVE REQUEST REFUSED: no live executor armed; "
            "see state/fleet.log and fix the failed interlock"
        )
    print(f"[fleet] mode={'LIVE' if co.live else 'PAPER'} agents={[a.name for a in co.agents]} "
          f"interval={interval}s data_simulated={co.feeds.simulated}")

    counter = {"n": 0}

    def on_cycle(c):
        counter["n"] += 1
        write_local_snapshot(c.state_path, "public/snapshot.js")
        if counter["n"] % max(1, args.dash_every) == 0:
            render_dashboard(c.state_path, "dashboard.html")

    try:
        co.run(cycles, interval, on_cycle=on_cycle)
    except KeyboardInterrupt:
        print("\n[fleet] interrupted — persisting state")
        co.ledger.persist()
    finally:
        try:
            render_dashboard(co.state_path, "dashboard.html")
            print("[fleet] dashboard written to dashboard.html")
        except Exception as e:
            print(f"[fleet] dashboard render failed: {e}")


if __name__ == "__main__":
    main()
