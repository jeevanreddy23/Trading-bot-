from __future__ import annotations

import time
from dataclasses import dataclass, field

BUY, SELL, CLOSE = "buy", "sell", "close"


@dataclass
class Signal:
    """A trade intention emitted by an agent. The risk manager sizes it; an executor fills it."""

    agent: str
    market: str                 # crypto | stocks | commodities | fx
    symbol: str                 # e.g. BTC/USDT, BHP.AX, GC=F, AUDUSD=X
    action: str                 # buy | sell (open short) | close
    conviction: float = 0.5     # 0..1, scales position size
    reason: str = ""
    price: float = 0.0          # reference price at signal time
    stop: float | None = None   # protective stop level (optional)
    venue: str | None = None    # exchange id for venue-specific fills (crypto arb)
    tag: str | None = None      # strategy tag / arb pair id (part of position identity)
    max_notional_aud: float | None = None  # hard cap this signal imposes on itself
    ts: float = field(default_factory=time.time)

    def label(self) -> str:
        v = f"@{self.venue}" if self.venue else ""
        return f"{self.action.upper()} {self.symbol}{v}"
