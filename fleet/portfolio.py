"""AUD-based portfolio ledger.

Positions are tracked CFD-style: opening a position moves only fees; equity is
cash + unrealized P&L; closing realizes P&L into cash. This gives one uniform
model across spot crypto, stocks, futures and FX for paper trading, and live
executors mirror their real fills into it.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass

from .util import quote_ccy, syd_date


@dataclass
class Position:
    symbol: str
    market: str
    qty: float              # +long / -short
    avg_price: float
    ccy: str
    agent: str
    opened_ts: float
    stop: float | None = None
    venue: str | None = None
    tag: str | None = None


class Ledger:
    def __init__(self, cfg: dict, state_dir: str):
        self.cfg = cfg
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "ledger.json")
        self.trades_path = os.path.join(state_dir, "trades.jsonl")
        self.cash = float(cfg.get("starting_equity", 10000))
        self.positions: dict[str, Position] = {}
        self.equity_series: list = []
        self.day = syd_date()
        self.day_start_equity = self.cash
        self.halted = False
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
            self.cash = d["cash"]
            self.positions = {k: Position(**p) for k, p in d["positions"].items()}
            self.equity_series = d.get("equity_series", [])[-5000:]
            self.day = d.get("day", self.day)
            self.day_start_equity = d.get("day_start_equity", self.cash)
            self.halted = d.get("halted", False)

    def persist(self):
        with open(self.path, "w") as f:
            json.dump(
                {
                    "cash": self.cash,
                    "positions": {k: asdict(p) for k, p in self.positions.items()},
                    "equity_series": self.equity_series[-5000:],
                    "day": self.day,
                    "day_start_equity": self.day_start_equity,
                    "halted": self.halted,
                },
                f,
                indent=1,
            )

    # ---------- FX conversion ----------
    def rates_to_aud(self, quotes: dict) -> dict:
        q = quotes.get("AUDUSD=X")
        audusd = (q.last if q and q.last else None) or 0.655
        rates = {"AUD": 1.0, "USD": 1.0 / audusd}
        jq = quotes.get("USDJPY=X")
        if jq and jq.last:
            rates["JPY"] = rates["USD"] / jq.last
        return rates

    @staticmethod
    def to_aud(value: float, ccy: str, rates: dict) -> float:
        return value * rates.get(ccy, rates["USD"])

    # ---------- position identity ----------
    @staticmethod
    def pos_key(symbol: str, tag: str | None = None, venue: str | None = None) -> str:
        return f"{symbol}|{venue or '-'}|{tag or '-'}"

    # ---------- valuation ----------
    def _mark(self, pos: Position, quotes: dict) -> float:
        q = None
        if pos.venue is not None:
            q = quotes.get((pos.symbol, pos.venue))
        q = q or quotes.get(pos.symbol)
        return (q.last if q and q.last else None) or pos.avg_price

    def unrealized_aud(self, pos: Position, quotes: dict, rates: dict) -> float:
        px = self._mark(pos, quotes)
        return self.to_aud(pos.qty * (px - pos.avg_price), pos.ccy, rates)

    def equity(self, quotes: dict) -> float:
        rates = self.rates_to_aud(quotes)
        return self.cash + sum(self.unrealized_aud(p, quotes, rates) for p in self.positions.values())

    def gross_exposure_aud(self, quotes: dict) -> float:
        rates = self.rates_to_aud(quotes)
        return sum(
            abs(p.qty) * self._mark(p, quotes) * rates.get(p.ccy, rates["USD"])
            for p in self.positions.values()
        )

    def market_exposure_aud(self, market: str, quotes: dict) -> float:
        rates = self.rates_to_aud(quotes)
        return sum(
            abs(p.qty) * self._mark(p, quotes) * rates.get(p.ccy, rates["USD"])
            for p in self.positions.values()
            if p.market == market
        )

    # ---------- day tracking ----------
    def roll_day(self, quotes: dict):
        d = syd_date()
        if d != self.day:
            self.day = d
            self.day_start_equity = self.equity(quotes)

    def daily_pnl(self, quotes: dict) -> float:
        return self.equity(quotes) - self.day_start_equity

    # ---------- trades ----------
    def record_trade(self, **kw):
        kw.setdefault("ts", time.time())
        with open(self.trades_path, "a") as f:
            f.write(json.dumps(kw) + "\n")

    def open_position(self, sig, qty: float, fill_px: float, fee_aud: float, mode: str) -> str:
        key = self.pos_key(sig.symbol, sig.tag, sig.venue)
        self.cash -= fee_aud
        signed = qty if sig.action == "buy" else -qty
        self.positions[key] = Position(
            sig.symbol, sig.market, signed, fill_px, quote_ccy(sig.symbol),
            sig.agent, time.time(), sig.stop, sig.venue, sig.tag,
        )
        self.record_trade(
            action=sig.action, symbol=sig.symbol, qty=round(signed, 8), price=fill_px,
            fee_aud=round(fee_aud, 4), agent=sig.agent, venue=sig.venue,
            reason=sig.reason, mode=mode,
        )
        return key

    def close_position(self, key: str, fill_px: float, fee_aud: float, quotes: dict,
                       mode: str, reason: str = "") -> float | None:
        pos = self.positions.pop(key, None)
        if pos is None:
            return None
        rates = self.rates_to_aud(quotes)
        pnl_aud = self.to_aud(pos.qty * (fill_px - pos.avg_price), pos.ccy, rates) - fee_aud
        self.cash += pnl_aud
        self.record_trade(
            action="close", symbol=pos.symbol, qty=round(-pos.qty, 8), price=fill_px,
            fee_aud=round(fee_aud, 4), agent=pos.agent, venue=pos.venue,
            reason=reason, pnl_aud=round(pnl_aud, 2), mode=mode,
        )
        return pnl_aud

    def snapshot(self, quotes: dict) -> float:
        eq = self.equity(quotes)
        self.equity_series.append([round(time.time(), 1), round(eq, 2)])
        self.equity_series = self.equity_series[-5000:]
        return eq

    def recent_trades(self, n: int = 30) -> list:
        try:
            with open(self.trades_path) as f:
                lines = f.readlines()[-n:]
        except FileNotFoundError:
            return []
        return [json.loads(ln) for ln in lines]
