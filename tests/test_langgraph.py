#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet.config import load_config
from fleet.coordinator import Coordinator
from fleet.dashboard import render_dashboard


def main() -> None:
    cfg = load_config()
    cfg["loop"]["state_dir"] = "state_test"
    coordinator = Coordinator(cfg, force_sim=True, reset=True, quiet=True)
    coordinator.feeds.refresh()
    agent = next(item for item in coordinator.agents if item.name == "langgraph_40")

    assert len(agent.node_names) == 40
    assert len(set(agent.node_names)) == 40
    assert len(agent.specialist_nodes) == 30
    assert len(agent.portfolio_nodes) == 10

    signals = agent.run(coordinator.ctx)
    assert "langgraph" in coordinator.ctx.state, agent.note
    state = coordinator.ctx.state["langgraph"]
    assert signals == [], "shadow graph emitted a trade intention"
    assert state["mode"] == "SHADOW"
    assert state["agent_count"] == 40
    assert state["specialists"] == 30
    assert state["portfolio_challengers"] == 10
    assert state["persistence"] == "memory"
    assert len(state["symbols"]) == 3
    assert len(state["decisions"]) == 3
    assert sum(len(item["votes"]) for item in state["decisions"]) == 30
    assert len(state["checks"]) == 10
    assert all(len(item["votes"]) == 10 for item in state["decisions"])
    assert all(item["risk_gate"] == "FAIL" for item in state["decisions"]), \
        "synthetic data passed the LangGraph proposal gate"
    assert state["best_trade"]["rank"] == 1
    assert not hasattr(agent, "execute"), "research graph gained an execution method"

    coordinator.write_state(coordinator.ledger.equity(coordinator.feeds.quotes))
    output = Path("state_test/langgraph-dashboard.html")
    render_dashboard(coordinator.state_path, str(output))
    dashboard = output.read_text(encoding="utf-8")
    assert "LangGraph 40-agent shadow ensemble" in dashboard
    assert '"agent_count": 40' in dashboard

    print("16/16 LangGraph 40-agent checks passed")


if __name__ == "__main__":
    main()
