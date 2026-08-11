from __future__ import annotations

import time


class Agent:
    name = "base"
    market = "?"
    interval = 60

    def __init__(self, cfg: dict, acfg: dict | None = None):
        self.cfg = cfg
        self.acfg = acfg or {}
        self.interval = self.acfg.get("interval", self.interval)
        self.last_run = 0.0
        self.note = ""

    def due(self) -> bool:
        return time.time() - self.last_run >= self.interval

    def run(self, ctx) -> list:
        self.last_run = time.time()
        try:
            return self.evaluate(ctx) or []
        except Exception as e:  # one broken agent must never take down the fleet
            self.note = f"error: {type(e).__name__}: {e}"
            return []

    def evaluate(self, ctx) -> list:
        return []
