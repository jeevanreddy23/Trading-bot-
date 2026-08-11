"""Kraken WebSocket v2 L2 book maintenance and CRC32 verification."""
from __future__ import annotations

import zlib
from decimal import Decimal


def _decimal_text(value) -> str:
    text = format(Decimal(str(value)), "f").replace(".", "").lstrip("0")
    return text or "0"


class OrderBook:
    def __init__(self, depth: int = 10):
        self.depth = depth
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.valid = False
        self.last_checksum: int | None = None

    def _apply_side(self, side: dict, updates: list[dict]) -> None:
        for level in updates:
            price, qty = Decimal(str(level["price"])), Decimal(str(level["qty"]))
            if qty == 0:
                side.pop(price, None)
            else:
                side[price] = qty

    def _truncate(self) -> None:
        self.asks = dict(sorted(self.asks.items())[: self.depth])
        self.bids = dict(sorted(self.bids.items(), reverse=True)[: self.depth])

    def checksum(self) -> int:
        asks = "".join(
            _decimal_text(price) + _decimal_text(qty)
            for price, qty in sorted(self.asks.items())[:10]
        )
        bids = "".join(
            _decimal_text(price) + _decimal_text(qty)
            for price, qty in sorted(self.bids.items(), reverse=True)[:10]
        )
        return zlib.crc32((asks + bids).encode()) & 0xFFFFFFFF

    def apply(self, payload: dict, snapshot: bool = False) -> bool:
        if snapshot:
            self.bids.clear()
            self.asks.clear()
        self._apply_side(self.bids, payload.get("bids", []))
        self._apply_side(self.asks, payload.get("asks", []))
        self._truncate()
        expected = payload.get("checksum")
        self.last_checksum = int(expected) if expected is not None else None
        self.valid = expected is not None and self.checksum() == int(expected)
        return self.valid

    def metrics(self) -> dict:
        bid = max(self.bids, default=Decimal(0))
        ask = min(self.asks, default=Decimal(0))
        mid = (bid + ask) / 2 if bid and ask else Decimal(0)
        spread_pct = ((ask - bid) / mid * 100) if mid else Decimal(0)
        bid_qty = sum(q for _, q in sorted(self.bids.items(), reverse=True)[:10])
        ask_qty = sum(q for _, q in sorted(self.asks.items())[:10])
        total = bid_qty + ask_qty
        imbalance = (bid_qty - ask_qty) / total if total else Decimal(0)
        return {
            "bid": float(bid), "ask": float(ask), "mid": float(mid),
            "spread_pct": float(spread_pct), "imbalance": float(imbalance),
            "checksum_valid": self.valid,
        }
