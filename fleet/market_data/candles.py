"""Bounded OHLC store shared by the Kraken stream and dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import pandas as pd


class CandleStore:
    def __init__(self, limit: int = 500):
        self.limit = limit
        self._rows: dict[str, dict[int, dict]] = defaultdict(dict)

    @staticmethod
    def _epoch(value: str) -> int:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())

    def update(self, item: dict) -> None:
        symbol = item["symbol"]
        ts = self._epoch(item.get("interval_begin") or item["timestamp"])
        self._rows[symbol][ts] = {
            "time": ts,
            "open": float(item["open"]), "high": float(item["high"]),
            "low": float(item["low"]), "close": float(item["close"]),
            "volume": float(item.get("volume", 0)),
        }
        keys = sorted(self._rows[symbol])[-self.limit :]
        self._rows[symbol] = {key: self._rows[symbol][key] for key in keys}

    def rows(self, symbol: str) -> list[dict]:
        return [self._rows[symbol][key] for key in sorted(self._rows.get(symbol, {}))]

    def frame(self, symbol: str) -> pd.DataFrame | None:
        rows = self.rows(symbol)
        if not rows:
            return None
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
        frame.attrs["source"] = "kraken-ws"
        return frame
