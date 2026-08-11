"""Coordinator: runs the agent fleet on a fixed cycle.

Each cycle: refresh feeds -> enforce stops/halt -> run due agents -> risk-check
and execute signals -> snapshot equity -> persist state + dashboard JSON.
"""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

from .agents import build_agents
from .config import dig
from .datafeeds import FeedRouter
from .execution.paper import PaperExecutor
from .portfolio import Ledger
from .risk import RiskManager
from .signals import Signal
from .util import now_syd, quote_ccy


class Coordinator:
    def __init__(self, cfg: dict, force_sim: bool = False, live: bool = False,
                 reset: bool = False, quiet: bool = False):
        self.cfg = cfg
        self.state_dir = dig(cfg, "loop.state_dir", "state")
        os.makedirs(self.state_dir, exist_ok=True)
        if reset:
            for fn in ("ledger.json", "trades.jsonl", "state.json"):
                p = os.path.join(self.state_dir, fn)
                if os.path.exists(p):
                    os.remove(p)

        self.feeds = FeedRouter(cfg, force_sim=force_sim, quiet=quiet)
        self.ledger = Ledger(cfg, self.state_dir)
        self.risk = RiskManager(cfg)
        self.agents = build_agents(cfg)
        self.ctx = SimpleNamespace(feeds=self.feeds, ledger=self.ledger, cfg=cfg, state={})
        self.state_path = os.path.join(self.state_dir, "state.json")
        self.log_path = os.path.join(self.state_dir, "fleet.log")
        self.quiet = quiet
        self.events: list = []

        self.live = False
        self.executors: dict = {"paper": PaperExecutor(cfg)}
        if live:
            self._arm_live()

    # ------------------------------------------------------------------ live
    def _arm_live(self):
        """Live trading arms only when every interlock passes."""
        if self.cfg.get("mode") != "live":
            self.log("[live] refused: config mode is not 'live'")
            return
        ack_var = dig(self.cfg, "execution.live.confirm_env", "LIVE_TRADING_ACK")
        if os.environ.get(ack_var) != "I_UNDERSTAND_THE_RISKS":
            self.log(f"[live] refused: env {ack_var} != I_UNDERSTAND_THE_RISKS")
            return
        if self.feeds.simulated:
            self.log("[live] refused: no live data feed reachable (sim only)")
            return
        armed = []
        markets = self.cfg.get("markets", {})
        if markets.get("crypto", {}).get("enabled", False):
            try:
                from .execution.ccxt_live import CcxtLiveExecutor
                self.executors["crypto"] = CcxtLiveExecutor(self.cfg)
                armed.append("crypto")
            except Exception as e:
                self.log(f"[live] crypto executor unavailable: {e}")
        if markets.get("fx", {}).get("enabled", False):
            try:
                from .execution.oanda_live import OandaLiveExecutor
                self.executors["fx"] = OandaLiveExecutor(self.cfg)
                armed.append("fx")
            except Exception as e:
                self.log(f"[live] fx executor unavailable: {e}")
        if (markets.get("stocks", {}).get("enabled", False)
                or markets.get("commodities", {}).get("enabled", False)):
            try:
                from .execution.ibkr_live import IbkrLiveExecutor
                ib = IbkrLiveExecutor(self.cfg)
                if markets.get("stocks", {}).get("enabled", False):
                    self.executors["stocks"] = ib
                if markets.get("commodities", {}).get("enabled", False):
                    self.executors["commodities"] = ib
                armed.append("stocks+commodities")
            except Exception as e:
                self.log(f"[live] ibkr executor unavailable: {e}")
        self.live = bool(armed)
        self.log(f"[live] ARMED for: {', '.join(armed) if armed else 'nothing'}; "
                 f"other markets stay paper")

    def executor_for(self, sig) -> tuple:
        """Return (executor, is_intended_mode). In live mode, markets without a
        live executor are NOT silently papered for opens — they are skipped."""
        if not self.live:
            return self.executors["paper"], True
        ex = self.executors.get(sig.market)
        if ex is not None:
            return ex, True
        # Never mutate a live ledger with a paper fill. If an executor is
        # unavailable, leave the position visible and require operator action.
        return None, False

    # ----------------------------------------------------------------- utils
    def log(self, msg: str):
        line = f"{now_syd().strftime('%H:%M:%S')} {msg}"
        if not self.quiet:
            print(line, flush=True)
        self.events.append(line)
        self.events = self.events[-200:]
        try:
            with open(self.log_path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------- stop-loss
    def stop_checks(self) -> list:
        sigs = []
        for key, pos in list(self.ledger.positions.items()):
            if pos.stop is None:
                continue
            q = (self.feeds.get_venue(pos.symbol, pos.venue) if pos.venue
                 else self.feeds.get(pos.symbol))
            if q is None or not q.last:
                continue
            if (pos.qty > 0 and q.last <= pos.stop) or (pos.qty < 0 and q.last >= pos.stop):
                sigs.append(Signal("risk_stop", pos.market, pos.symbol, "close", 1.0,
                                   f"stop {pos.stop:g} hit", q.last,
                                   venue=pos.venue, tag=pos.tag))
        return sigs

    def flatten_all(self, reason: str) -> list:
        return [Signal("risk_halt", p.market, p.symbol, "close", 1.0, reason,
                       0.0, venue=p.venue, tag=p.tag)
                for p in self.ledger.positions.values()]

    # ------------------------------------------------------------ execution
    def _exec(self, sig, qty: float):
        ex, ok = self.executor_for(sig)
        if not ok:
            self.log(f"~ {sig.agent} {sig.label()}: no live executor for {sig.market}, skipped")
            return
        fill = ex.execute(sig, qty, self.ctx)
        mark = "+" if fill.ok else "x"
        self.log(f"{mark} [{ex.mode}] {sig.agent} {sig.label()}: {fill.info}")

    def process_signals(self, signals: list):
        groups: dict = {}
        singles: list = []
        for s in signals:
            if s.tag and s.tag.startswith("arb-") and s.action in ("buy", "sell"):
                groups.setdefault(s.tag, []).append(s)
            else:
                singles.append(s)

        # arb pairs are atomic: both legs approve or neither trades
        for tag, legs in groups.items():
            if len(legs) != 2:
                continue
            evals = [self.risk.evaluate(s, self.ledger, self.feeds.quotes) for s in legs]
            if any(q <= 0 for q, _ in evals):
                reasons = "; ".join(r for _, r in evals)
                self.log(f"x arb {tag} rejected ({reasons})")
                continue
            rates = self.ledger.rates_to_aud(self.feeds.quotes)
            notionals = [q * s.price * rates.get(quote_ccy(s.symbol), rates["USD"])
                         for (q, _), s in zip(evals, legs)]
            common = min(notionals)
            for s in legs:
                r = rates.get(quote_ccy(s.symbol), rates["USD"])
                self._exec(s, common / (s.price * r))

        for s in singles:
            if s.action == "close":
                self._exec(s, 0.0)
                continue
            qty, reason = self.risk.evaluate(s, self.ledger, self.feeds.quotes)
            if qty <= 0:
                self.log(f"x {s.agent} {s.label()}: {reason}")
                continue
            self._exec(s, qty)

    # ----------------------------------------------------------------- cycle
    def cycle(self) -> float:
        self.feeds.refresh()
        self.ledger.roll_day(self.feeds.quotes)

        halted = self.risk.check_halt(self.ledger, self.feeds.quotes)
        kill = self.risk.kill_switch()
        signals = self.stop_checks()
        if (halted or kill) and self.ledger.positions:
            why = "drawdown kill-switch" if halted else "manual KILL file"
            self.log(f"! HALT: flattening all positions ({why})")
            signals = self.flatten_all(why) + signals
        if not (halted or kill):
            for ag in self.agents:
                if ag.due():
                    signals += ag.run(self.ctx)

        self.process_signals(signals)
        eq = self.ledger.snapshot(self.feeds.quotes)
        self.ledger.persist()
        self.write_state(eq)
        return eq

    def run(self, cycles: int, interval: float, on_cycle=None):
        for i in range(cycles):
            t0 = time.time()
            eq = self.cycle()
            day = self.ledger.daily_pnl(self.feeds.quotes)
            self.log(f"cycle {i + 1}/{cycles}  equity A${eq:,.2f}  day {day:+,.2f}  "
                     f"open {len(self.ledger.positions)}")
            if on_cycle:
                try:
                    on_cycle(self)
                except Exception:
                    pass
            if i < cycles - 1:
                time.sleep(max(0.0, interval - (time.time() - t0)))

    # ----------------------------------------------------------------- state
    def write_state(self, eq: float):
        rates = self.ledger.rates_to_aud(self.feeds.quotes)
        positions = []
        for key, p in self.ledger.positions.items():
            upnl = self.ledger.unrealized_aud(p, self.feeds.quotes, rates)
            positions.append({
                "key": key, "symbol": p.symbol, "market": p.market,
                "qty": round(p.qty, 8), "avg_price": p.avg_price,
                "mark": self.ledger._mark(p, self.feeds.quotes),
                "upnl_aud": round(upnl, 2), "agent": p.agent,
                "venue": p.venue, "tag": p.tag, "stop": p.stop,
            })
        state = {
            "ts": time.time(),
            "generated_syd": now_syd().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "mode": "LIVE" if self.live else "PAPER",
            "data_sources": self.feeds.source_status,
            "simulated_data": self.feeds.simulated,
            "equity_aud": round(eq, 2),
            "cash_aud": round(self.ledger.cash, 2),
            "starting_equity": self.cfg.get("starting_equity", 10000),
            "day_pnl_aud": round(self.ledger.daily_pnl(self.feeds.quotes), 2),
            "halted": self.ledger.halted,
            "positions": positions,
            "equity_series": self.ledger.equity_series[-1500:],
            "arb": self.ctx.state.get("arb", []),
            "agents": [{"name": a.name, "market": a.market, "interval": a.interval,
                        "note": a.note} for a in self.agents],
            "recent_trades": self.ledger.recent_trades(25),
            "events": self.events[-40:],
            "risk": {k: self.cfg["risk"][k] for k in
                     ("max_daily_loss_pct", "kill_drawdown_pct", "max_gross_leverage",
                      "max_position_pct_equity", "max_open_positions")},
        }
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=1)
