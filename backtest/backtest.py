#!/usr/bin/env python3
"""Vectorised backtests of the fleet's rule-sets on daily bars.

Run on YOUR machine (real Yahoo data):   python backtest/backtest.py
Offline engine self-test (synthetic):    python backtest/backtest.py --sim

Costs default to 10 bps per side. Results on synthetic data prove the engine
runs — they say NOTHING about real edge. Only real-data results matter, and
even those are in-sample history, not a promise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet.config import load_config          # noqa: E402
from fleet.datafeeds import FeedRouter        # noqa: E402
from fleet.indicators import ema, rsi, sma, zscore  # noqa: E402


def positions_momentum(df: pd.DataFrame) -> pd.Series:
    c = df["close"]
    pos = ((c > sma(c, 50)) & (sma(c, 20) > sma(c, 50))).astype(float)
    return pos.shift(1).fillna(0)


def positions_ema_cross(df: pd.DataFrame) -> pd.Series:
    c = df["close"]
    pos = (ema(c, 12) > ema(c, 26)).astype(float)
    return pos.shift(1).fillna(0)


def positions_donchian(df: pd.DataFrame, allow_short=True) -> pd.Series:
    c = df["close"].values
    cs = pd.Series(c)
    hi20 = cs.rolling(20).max().shift(1).values
    lo10 = cs.rolling(10).min().shift(1).values
    lo20 = cs.rolling(20).min().shift(1).values
    hi10 = cs.rolling(10).max().shift(1).values
    pos = np.zeros(len(c))
    p = 0.0
    for i in range(len(c)):
        if np.isnan(hi20[i]):
            pos[i] = 0
            continue
        if p == 0:
            if c[i] >= hi20[i]:
                p = 1
            elif allow_short and c[i] <= lo20[i]:
                p = -1
        elif p == 1 and c[i] <= lo10[i]:
            p = 0
        elif p == -1 and c[i] >= hi10[i]:
            p = 0
        pos[i] = p
    return pd.Series(pos, index=df.index).shift(1).fillna(0)


def positions_zscore(df: pd.DataFrame) -> pd.Series:
    z = zscore(df["close"], 20).values
    pos = np.zeros(len(z))
    p = 0.0
    for i in range(len(z)):
        if np.isnan(z[i]):
            pos[i] = 0
            continue
        if p == 0:
            if z[i] < -2:
                p = 1
            elif z[i] > 2:
                p = -1
        elif abs(z[i]) < 0.5:
            p = 0
        pos[i] = p
    return pd.Series(pos, index=df.index).shift(1).fillna(0)


STRATS = {
    "stocks": ("momentum SMA20/50", positions_momentum),
    "crypto": ("EMA12/26 trend", positions_ema_cross),
    "commodities": ("Donchian 20/10", positions_donchian),
    "fx": ("z-score reversion", positions_zscore),
}


def metrics(rets: pd.Series, pos: pd.Series) -> dict:
    eq = (1 + rets).cumprod()
    total = eq.iloc[-1] - 1
    yrs = max(len(rets) / 252, 1e-9)
    cagr = (1 + total) ** (1 / yrs) - 1
    vol = rets.std(ddof=0) * np.sqrt(252)
    sharpe = (rets.mean() * 252) / vol if vol > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    trades = int((pos.diff().abs() > 0).sum())
    return dict(total_pct=round(total * 100, 1), cagr_pct=round(cagr * 100, 1),
                sharpe=round(float(sharpe), 2), max_dd_pct=round(float(dd) * 100, 1),
                trades=trades, exposure_pct=round(float((pos != 0).mean()) * 100, 0))


def run(cfg, force_sim: bool, cost_bps: float = 10.0):
    feeds = FeedRouter(cfg, force_sim=force_sim, quiet=True)
    m = cfg["markets"]
    groups = {
        "stocks": (m["stocks"].get("asx", []) + m["stocks"].get("us", []))
        if m["stocks"].get("enabled") else [],
        "crypto": m["crypto"].get("momentum_symbols", []) if m["crypto"].get("enabled") else [],
        "commodities": m["commodities"].get("symbols", []) if m["commodities"].get("enabled") else [],
        "fx": m["fx"].get("symbols", []) if m["fx"].get("enabled") else [],
    }
    rows = []
    for market, syms in groups.items():
        label, fn = STRATS[market]
        for sym in syms:
            df = feeds.get_ohlcv(sym, "1d", 500)
            if df is None or len(df) < 120:
                continue
            pos = fn(df)
            r = df["close"].pct_change().fillna(0)
            strat = pos * r - pos.diff().abs().fillna(0) * cost_bps / 1e4
            mt = metrics(strat, pos)
            bh = metrics(r, pd.Series(1.0, index=r.index))
            rows.append(dict(market=market, strategy=label, symbol=sym, **mt,
                             buyhold_total_pct=bh["total_pct"], bars=len(df),
                             data_source="synthetic" if feeds.simulated else "real"))
    return rows, feeds.simulated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="force synthetic data")
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    rows, simulated = run(cfg, args.sim, args.cost_bps)

    src = "SYNTHETIC (engine self-test only — no real-edge information)" if simulated \
        else "real historical data (in-sample; past ≠ future)"
    print(f"\nBacktest — daily bars, {args.cost_bps:g} bps/side costs — data: {src}\n")
    hdr = f"{'market':<12} {'symbol':<10} {'strategy':<18} {'total%':>8} {'CAGR%':>7} " \
          f"{'Sharpe':>7} {'maxDD%':>7} {'trades':>7} {'expo%':>6} {'B&H%':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['market']:<12} {r['symbol']:<10} {r['strategy']:<18} "
              f"{r['total_pct']:>8.1f} {r['cagr_pct']:>7.1f} {r['sharpe']:>7.2f} "
              f"{r['max_dd_pct']:>7.1f} {r['trades']:>7d} {r['exposure_pct']:>6.0f} "
              f"{r['buyhold_total_pct']:>8.1f}")
    os.makedirs("results", exist_ok=True)
    with open("results/backtest.json", "w") as f:
        json.dump({"cost_bps": args.cost_bps, "synthetic": simulated, "rows": rows}, f, indent=1)
    print(f"\nSaved results/backtest.json ({len(rows)} symbol runs)")


if __name__ == "__main__":
    main()
