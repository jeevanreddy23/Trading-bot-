"""Forty-node LangGraph crypto research ensemble.

Thirty symbol specialists (ten for each configured Kraken pair) fan out in
parallel with ten portfolio challengers. The graph can propose one ranked
trade, but it never talks to Kraken and cannot bypass Coordinator.process_signals
or the deterministic RiskManager.
"""
from __future__ import annotations

import math
import operator
import os
import time
import uuid
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from ..config import dig
from ..indicators import atr, ema, rsi, sma, zscore
from ..signals import Signal
from .base import Agent


SPECIALISTS = (
    "regime", "momentum", "reversal", "volatility", "ema_cross",
    "breakout", "rsi_confirmation", "trend_strength", "volume_flow", "liquidity",
)
PORTFOLIO_CHALLENGERS = (
    "data_freshness", "source_integrity", "spread", "correlation", "drawdown",
    "daily_loss", "position_count", "gross_exposure", "market_exposure", "kill_switch",
)
WEIGHTS = {
    "regime": 1.15, "momentum": 1.25, "reversal": 0.75, "volatility": 0.0,
    "ema_cross": 1.0, "breakout": 0.9, "rsi_confirmation": 0.7,
    "trend_strength": 0.9, "volume_flow": 0.65, "liquidity": 0.35,
}
BLOCKING_PORTFOLIO_CHECKS = {
    "drawdown", "daily_loss", "position_count", "gross_exposure",
    "market_exposure", "kill_switch",
}


class GraphState(TypedDict):
    cycle_id: str
    symbols: list[str]
    markets: dict[str, dict]
    portfolio: dict
    votes: Annotated[list[dict], operator.add]
    checks: Annotated[list[dict], operator.add]
    decisions: dict[str, dict]
    best_trade: dict | None


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value))) if math.isfinite(float(value)) else 0.0


def _frame(market: dict) -> pd.DataFrame | None:
    rows = market.get("candles") or []
    if len(rows) < 60:
        return None
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
    return frame


def _row(symbol: str, strategy: str, label: str, confidence: float, score: float,
         reason: str, veto: bool = False) -> dict:
    return {
        "agent": f"{symbol}:{strategy}", "symbol": symbol, "strategy": strategy,
        "label": label, "confidence": round(_clip(confidence, 0.0, 1.0), 3),
        "score": round(_clip(score), 3), "reason": reason, "veto": bool(veto),
    }


def _specialist_vote(symbol: str, strategy: str, market: dict, cfg: dict) -> dict:
    frame = _frame(market)
    if frame is None:
        return _row(symbol, strategy, "NO DATA", 0.0, 0.0, "fewer than 60 candles", True)
    close = frame["close"]
    px = float(close.iloc[-1])
    atr_value = max(float(atr(frame, 14).iloc[-1]), px * 1e-8)
    atr_pct = atr_value / max(px, 1e-12) * 100

    if strategy == "regime":
        fast, slow = ema(close, 20), ema(close, 50)
        separation = (float(fast.iloc[-1]) - float(slow.iloc[-1])) / atr_value
        slope = (float(slow.iloc[-1]) - float(slow.iloc[-6])) / atr_value
        score = _clip((separation + slope) / 2)
        label = "TRENDING UP" if score > 0.15 else "TRENDING DOWN" if score < -0.15 else "RANGING"
        return _row(symbol, strategy, label, 0.5 + abs(score) * 0.45, score,
                    f"EMA20/50 {separation:+.2f} ATR; slope {slope:+.2f} ATR")

    if strategy == "momentum":
        e12, e26 = ema(close, 12), ema(close, 26)
        spread = (float(e12.iloc[-1]) - float(e26.iloc[-1])) / atr_value
        value = float(rsi(close, 14).iloc[-1])
        score = _clip(spread / 2)
        if value > 78:
            score = min(score, 0.15)
        elif value < 22:
            score = max(score, -0.15)
        label = "LONG" if score > 0.12 else "SHORT" if score < -0.12 else "NEUTRAL"
        return _row(symbol, strategy, label, 0.5 + abs(score) * 0.45, score,
                    f"EMA12/26 {spread:+.2f} ATR; RSI {value:.1f}")

    if strategy == "reversal":
        value = float(zscore(close, 20).iloc[-1])
        score = _clip(-value / 2.5)
        label = "LONG" if score > 0.4 else "SHORT" if score < -0.4 else "NEUTRAL"
        return _row(symbol, strategy, label, 0.45 + min(abs(value), 2.7) * 0.18,
                    score, f"20-bar z-score {value:+.2f}")

    if strategy == "volatility":
        limit = float(cfg.get("max_atr_pct", 4.0))
        acceptable = atr_pct <= limit
        confidence = _clip(1 - atr_pct / max(limit * 1.5, 0.01), 0.05, 0.99)
        return _row(symbol, strategy, "ACCEPTABLE" if acceptable else "HIGH",
                    confidence, 0.0, f"ATR14 {atr_pct:.2f}%", not acceptable)

    if strategy == "ema_cross":
        fast, slow = ema(close, 9), ema(close, 21)
        score = _clip((float(fast.iloc[-1]) - float(slow.iloc[-1])) / (2 * atr_value))
        label = "BULLISH" if score > 0.1 else "BEARISH" if score < -0.1 else "FLAT"
        return _row(symbol, strategy, label, 0.5 + abs(score) * 0.4, score,
                    f"EMA9/21 distance {score * 2:+.2f} ATR")

    if strategy == "breakout":
        upper = float(frame["high"].iloc[-21:-1].max())
        lower = float(frame["low"].iloc[-21:-1].min())
        score = _clip((px - (upper + lower) / 2) / max((upper - lower) / 2, atr_value))
        label = "BREAKOUT" if px >= upper else "BREAKDOWN" if px <= lower else "INSIDE"
        return _row(symbol, strategy, label, 0.45 + abs(score) * 0.4, score,
                    f"20h channel {lower:.6g}-{upper:.6g}")

    if strategy == "rsi_confirmation":
        value = float(rsi(close, 14).iloc[-1])
        score = _clip((value - 50) / 30)
        if value > 80 or value < 20:
            score *= 0.35
        label = "CONFIRM LONG" if score > 0.15 else "CONFIRM SHORT" if score < -0.15 else "NEUTRAL"
        return _row(symbol, strategy, label, 0.45 + abs(score) * 0.4, score,
                    f"RSI14 {value:.1f}")

    if strategy == "trend_strength":
        baseline = sma(close, 30)
        slope = (float(baseline.iloc[-1]) - float(baseline.iloc[-7])) / (6 * atr_value)
        location = (px - float(baseline.iloc[-1])) / (2 * atr_value)
        score = _clip((slope + location) / 2)
        label = "UP" if score > 0.1 else "DOWN" if score < -0.1 else "WEAK"
        return _row(symbol, strategy, label, 0.45 + abs(score) * 0.4, score,
                    f"SMA30 slope {slope:+.2f}; location {location:+.2f}")

    if strategy == "volume_flow":
        returns = close.pct_change().tail(18).fillna(0.0)
        volume = frame["volume"].tail(18).fillna(0.0)
        baseline = max(float(volume.mean()), 1e-12)
        signed_flow = float((np.sign(returns) * volume / baseline).mean())
        score = _clip(signed_flow)
        label = "BUY PRESSURE" if score > 0.12 else "SELL PRESSURE" if score < -0.12 else "BALANCED"
        return _row(symbol, strategy, label, 0.4 + abs(score) * 0.45, score,
                    f"18h signed relative volume {signed_flow:+.2f}")

    spread = float(market.get("spread_pct", 999.0))
    max_spread = float(cfg.get("max_spread_pct", 0.25))
    book = market.get("book") or {}
    imbalance = _clip(float(book.get("imbalance", 0.0)))
    age = float(market.get("quote_age_seconds", 1e9))
    fresh = age <= float(cfg.get("max_quote_age_seconds", 45))
    source_live = not str(market.get("source", "sim")).startswith("sim")
    passed = spread <= max_spread and fresh and source_live
    label = "LIQUID" if passed else "BLOCK"
    return _row(symbol, strategy, label, 0.75 if passed else 0.98, imbalance,
                f"spread {spread:.4f}%; age {age:.1f}s; source {market.get('source')}", not passed)


def _portfolio_check(name: str, state: GraphState) -> dict:
    markets, portfolio = state["markets"], state["portfolio"]
    risk = portfolio["risk"]
    values = list(markets.values())
    passed, reason = True, "ok"

    if name == "data_freshness":
        worst = max((float(row.get("quote_age_seconds", 1e9)) for row in values), default=1e9)
        passed = worst <= float(risk.get("max_quote_age_seconds", 45))
        reason = f"worst quote age {worst:.1f}s"
    elif name == "source_integrity":
        bad = [row.get("symbol") for row in values if str(row.get("source", "sim")).startswith("sim")]
        passed, reason = not bad, f"synthetic symbols {bad}" if bad else "all sources non-synthetic"
    elif name == "spread":
        worst = max((float(row.get("spread_pct", 999)) for row in values), default=999)
        passed = worst <= float(risk.get("max_spread_pct", 0.25))
        reason = f"worst spread {worst:.4f}%"
    elif name == "correlation":
        series = []
        for row in values:
            frame = _frame(row)
            if frame is not None:
                series.append(frame["close"].pct_change().tail(60).reset_index(drop=True))
        corr = pd.concat(series, axis=1).corr().abs() if len(series) >= 2 else pd.DataFrame()
        pairs = corr.where(np.triu(np.ones(corr.shape), 1).astype(bool)).stack()
        average = _clip(float(pairs.mean()), 0.0, 1.0) if len(pairs) else 0.0
        passed = average <= float(portfolio.get("max_pair_correlation", 0.92))
        reason = f"average absolute 1h correlation {average:.2f}"
    elif name == "drawdown":
        value = float(portfolio.get("drawdown_pct", 0))
        passed, reason = value < float(risk["kill_drawdown_pct"]), f"drawdown {value:.2f}%"
    elif name == "daily_loss":
        equity = max(float(portfolio.get("equity_aud", 0)), 1e-12)
        value = float(portfolio.get("daily_pnl_aud", 0)) / equity * 100
        passed, reason = value > -float(risk["max_daily_loss_pct"]), f"daily P&L {value:+.2f}%"
    elif name == "position_count":
        value = int(portfolio.get("position_count", 0))
        passed, reason = value < int(risk["max_open_positions"]), f"positions {value}/{risk['max_open_positions']}"
    elif name == "gross_exposure":
        value = float(portfolio.get("gross_exposure_aud", 0))
        limit = float(portfolio.get("equity_aud", 0)) * float(risk["max_gross_leverage"])
        passed, reason = value <= limit, f"gross A${value:.2f}/A${limit:.2f}"
    elif name == "market_exposure":
        value = float(portfolio.get("crypto_exposure_aud", 0))
        limit = float(portfolio.get("equity_aud", 0)) * float(risk["max_market_exposure_pct"]) / 100
        passed, reason = value <= limit, f"crypto A${value:.2f}/A${limit:.2f}"
    elif name == "kill_switch":
        passed = not portfolio.get("halted") and not portfolio.get("kill_switch")
        reason = "clear" if passed else "halted or KILL file present"

    return {
        "agent": f"portfolio:{name}", "check": name, "passed": bool(passed),
        "blocking": name in BLOCKING_PORTFOLIO_CHECKS, "reason": reason,
    }


def _aggregate(state: GraphState) -> dict:
    cfg = state["portfolio"]["agent_config"]
    portfolio_pass = all(row["passed"] for row in state["checks"] if row["blocking"])
    decisions = {}
    for symbol in state["symbols"]:
        market = state["markets"].get(symbol, {})
        votes = [row for row in state["votes"] if row["symbol"] == symbol]
        directional = [row for row in votes if WEIGHTS.get(row["strategy"], 0) > 0]
        denominator = sum(WEIGHTS[row["strategy"]] * row["confidence"] for row in directional)
        score = (sum(WEIGHTS[row["strategy"]] * row["confidence"] * row["score"]
                     for row in directional) / denominator if denominator else 0.0)
        long_probability = _clip(0.5 + score * 0.45, 0.01, 0.99)
        action = "LONG" if long_probability >= 0.5 else "SHORT"
        probability = max(long_probability, 1 - long_probability)
        spread = float(market.get("spread_pct", 999))
        atr_pct = float(market.get("atr_pct", 0))
        ev = abs(score) * atr_pct - float(cfg.get("round_trip_fees_pct", 0.8)) - spread
        vetoes = [row["agent"] for row in votes if row["veto"]]
        checks = {
            "data_complete": len(votes) == len(SPECIALISTS),
            "source_live": not str(market.get("source", "sim")).startswith("sim"),
            "quote_fresh": float(market.get("quote_age_seconds", 1e9)) <= float(cfg.get("max_quote_age_seconds", 45)),
            "spread": spread <= float(cfg.get("max_spread_pct", 0.25)),
            "specialist_vetoes_clear": not vetoes,
            "portfolio_gate": portfolio_pass,
            "probability": probability >= float(cfg.get("min_probability", 0.68)),
            "expected_value": ev >= float(cfg.get("min_ev_pct", 0.08)),
            "long_only": action == "LONG",
        }
        passed = all(checks.values())
        px = float(market.get("last", 0))
        atr_value = float(market.get("atr", 0))
        decisions[symbol] = {
            "symbol": symbol, "action": action, "long_probability": round(long_probability, 3),
            "probability": round(probability, 3), "ensemble_score": round(score, 3),
            "expected_value_pct": round(ev, 3), "spread_pct": round(spread, 4),
            "entry": round(px, 8), "stop": round(px - 1.5 * atr_value, 8),
            "target": round(px + 2.5 * atr_value, 8),
            "risk_gate": "PASS" if passed else "FAIL", "checks": checks,
            "vetoes": vetoes, "votes": votes,
            "deterministic_risk": {"status": "PENDING", "reason": "shadow proposal"},
        }
    ranked = sorted(decisions.values(), key=lambda row: (
        row["risk_gate"] == "PASS", row["expected_value_pct"], row["probability"]
    ), reverse=True)
    for index, decision in enumerate(ranked, 1):
        decision["rank"] = index
    return {"decisions": decisions, "best_trade": ranked[0] if ranked else None}


class CryptoLangGraphAgent(Agent):
    name = "langgraph_40"
    market = "crypto"
    interval = 300

    def __init__(self, cfg: dict, acfg: dict | None = None):
        super().__init__(cfg, acfg)
        self.symbol_slots = 3
        self.specialist_nodes = [
            f"symbol_{slot + 1}_{strategy}"
            for slot in range(self.symbol_slots) for strategy in SPECIALISTS
        ]
        self.portfolio_nodes = [f"portfolio_{name}" for name in PORTFOLIO_CHALLENGERS]
        self.node_names = self.specialist_nodes + self.portfolio_nodes
        builder = StateGraph(GraphState)
        for slot in range(self.symbol_slots):
            for strategy in SPECIALISTS:
                name = f"symbol_{slot + 1}_{strategy}"
                builder.add_node(name, self._make_specialist(slot, strategy))
                builder.add_edge(START, name)
        for check in PORTFOLIO_CHALLENGERS:
            name = f"portfolio_{check}"
            builder.add_node(name, self._make_challenger(check))
            builder.add_edge(START, name)
        builder.add_node("aggregate", _aggregate)
        builder.add_edge(self.node_names, "aggregate")
        builder.add_edge("aggregate", END)
        self.builder = builder
        self.local_graph = builder.compile()
        self._postgres_ready = False
        self.checkpoint_marker = Path(dig(cfg, "loop.state_dir", "state")) / "langgraph_thread_id"

    def _make_specialist(self, slot: int, strategy: str):
        def node(state: GraphState) -> dict:
            if slot >= len(state["symbols"]):
                return {"votes": []}
            symbol = state["symbols"][slot]
            return {"votes": [_specialist_vote(
                symbol, strategy, state["markets"].get(symbol, {}),
                state["portfolio"]["agent_config"],
            )]}
        return node

    @staticmethod
    def _make_challenger(check: str):
        def node(state: GraphState) -> dict:
            return {"checks": [_portfolio_check(check, state)]}
        return node

    @staticmethod
    def _postgres_conninfo() -> str | None:
        if not os.getenv("PGHOST"):
            return None
        from psycopg.conninfo import make_conninfo
        return make_conninfo(
            host=os.getenv("PGHOST"), port=os.getenv("PGPORT", "5432"),
            dbname=os.getenv("PGDATABASE", "fleet"), user=os.getenv("PGUSER", "fleet"),
            password=os.getenv("PGPASSWORD", ""),
        )

    def _invoke(self, initial: GraphState, thread_id: str) -> tuple[dict, str]:
        config = {
            "configurable": {"thread_id": thread_id},
            "max_concurrency": int(self.acfg.get("max_concurrency", 12)),
        }
        conninfo = self._postgres_conninfo()
        if conninfo:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                with PostgresSaver.from_conn_string(conninfo) as saver:
                    if not self._postgres_ready:
                        saver.setup()
                        self._postgres_ready = True
                    graph = self.builder.compile(checkpointer=saver)
                    result = graph.invoke(initial, config)
                    try:
                        previous = self.checkpoint_marker.read_text(encoding="utf-8").strip()
                    except OSError:
                        previous = ""
                    self.checkpoint_marker.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.checkpoint_marker.with_suffix(".tmp")
                    temporary.write_text(thread_id, encoding="utf-8")
                    os.replace(temporary, self.checkpoint_marker)
                    if previous and previous != thread_id:
                        try:
                            saver.delete_thread(previous)
                        except Exception:
                            pass
                    return result, "postgres"
            except Exception as exc:
                result = self.local_graph.invoke(initial, config)
                return result, f"memory-fallback ({type(exc).__name__})"
        return self.local_graph.invoke(initial, config), "memory"

    def evaluate(self, ctx) -> list:
        configured = list(ctx.cfg["markets"]["crypto"].get("momentum_symbols", []))
        symbols = configured[:self.symbol_slots]
        markets = {}
        now = time.time()
        for symbol in symbols:
            frame = ctx.feeds.get_ohlcv(symbol, "1h", 180)
            quote = ctx.feeds.get(symbol)
            if frame is None or quote is None or len(frame) < 60:
                markets[symbol] = {"symbol": symbol, "candles": [], "source": "missing"}
                continue
            atr_value = float(atr(frame, 14).iloc[-1])
            spread = ((quote.ask - quote.bid) / ((quote.ask + quote.bid) / 2) * 100
                      if quote.ask and quote.bid else 999.0)
            book = getattr(ctx.feeds.kraken_ws, "payload", {}).get("books", {}).get(symbol, {})
            markets[symbol] = {
                "symbol": symbol, "last": float(quote.last), "bid": quote.bid, "ask": quote.ask,
                "spread_pct": spread, "source": quote.source,
                "quote_age_seconds": max(0.0, now - float(quote.ts)),
                "atr": atr_value, "atr_pct": atr_value / max(float(quote.last), 1e-12) * 100,
                "book": book,
                "candles": [
                    {"time": int(ts.timestamp()), "open": float(row.open), "high": float(row.high),
                     "low": float(row.low), "close": float(row.close), "volume": float(row.volume)}
                    for ts, row in frame.tail(180).iterrows()
                ],
            }

        equity = ctx.ledger.equity(ctx.feeds.quotes)
        peak = max((value for _, value in ctx.ledger.equity_series), default=equity)
        portfolio = {
            "equity_aud": equity, "daily_pnl_aud": ctx.ledger.daily_pnl(ctx.feeds.quotes),
            "drawdown_pct": ((peak - equity) / peak * 100 if peak > 0 else 0),
            "position_count": len(ctx.ledger.positions),
            "gross_exposure_aud": ctx.ledger.gross_exposure_aud(ctx.feeds.quotes),
            "crypto_exposure_aud": ctx.ledger.market_exposure_aud("crypto", ctx.feeds.quotes),
            "halted": ctx.ledger.halted, "kill_switch": os.path.exists(ctx.risk.kill_file) if hasattr(ctx, "risk") else False,
            "risk": ctx.cfg["risk"], "agent_config": self.acfg,
            "max_pair_correlation": float(self.acfg.get("max_pair_correlation", 0.92)),
        }
        cycle_id = f"lg40-{int(now)}-{uuid.uuid4().hex[:8]}"
        initial: GraphState = {
            "cycle_id": cycle_id, "symbols": symbols, "markets": markets,
            "portfolio": portfolio, "votes": [], "checks": [],
            "decisions": {}, "best_trade": None,
        }
        result, persistence = self._invoke(initial, cycle_id)
        configured_shadow = bool(self.acfg.get("shadow_only", True))
        live_ack = os.getenv("LANGGRAPH_LIVE_ACK") == "I_UNDERSTAND_40_AGENT_RISK"
        shadow = configured_shadow or (getattr(ctx, "live", False) and not live_ack)
        decisions = sorted(result.get("decisions", {}).values(), key=lambda row: row.get("rank", 99))
        snapshot = {
            "cycle_id": cycle_id, "generated_ts": now, "agent_count": len(self.node_names),
            "specialists": len(self.specialist_nodes), "portfolio_challengers": len(self.portfolio_nodes),
            "mode": "SHADOW" if shadow else "ACTIVE", "persistence": persistence,
            "symbols": symbols, "checks": result.get("checks", []),
            "decisions": decisions, "best_trade": result.get("best_trade"),
        }
        ctx.state["langgraph"] = snapshot
        best = snapshot["best_trade"]
        self.note = (f"40 nodes | {snapshot['mode']} | {persistence} | "
                     f"best {best['symbol']} {best['action']} p{best['probability']:.2f} {best['risk_gate']}"
                     if best else f"40 nodes | {snapshot['mode']} | no candidate")
        if shadow or not best or best["risk_gate"] != "PASS":
            return []
        if getattr(ctx, "live", False) and persistence != "postgres":
            self.note += " | live proposal blocked: checkpoint database unavailable"
            return []
        key = ctx.ledger.pos_key(best["symbol"], "langgraph-40")
        if key in ctx.ledger.positions:
            if best["long_probability"] < float(self.acfg.get("exit_probability", 0.45)):
                return [Signal(self.name, "crypto", best["symbol"], "close", 1.0,
                               "LangGraph long probability deteriorated", best["entry"],
                               tag="langgraph-40")]
            return []
        return [Signal(
            self.name, "crypto", best["symbol"], "buy", best["probability"],
            f"40-agent rank 1; p={best['probability']:.2f}; EV={best['expected_value_pct']:+.2f}%",
            best["entry"], stop=best["stop"], tag="langgraph-40",
        )]
