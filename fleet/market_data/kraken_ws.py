"""Public Kraken WebSocket v2 collector.

No API key is used. The process writes a bounded, atomic JSON snapshot that
the fleet consumes read-only. Invalid L2 checksums are never published.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import websockets

from .candles import CandleStore
from .orderbook import OrderBook

URL = "wss://ws.kraken.com/v2"


class KrakenStream:
    def __init__(self, symbols: list[str], output: str, depth: int = 10):
        self.symbols = symbols
        self.output = Path(output)
        self.depth = depth
        self.books = {symbol: OrderBook(depth) for symbol in symbols}
        self.candles = CandleStore(500)
        self.quotes: dict[str, dict] = {}
        self.trades: dict[str, list] = {symbol: [] for symbol in symbols}
        self.connected_at = 0.0
        self.last_message = 0.0
        self.error = ""

    def subscriptions(self) -> list[dict]:
        return [
            {"method": "subscribe", "params": {"channel": "ticker", "symbol": self.symbols,
                                                   "event_trigger": "bbo", "snapshot": True}},
            {"method": "subscribe", "params": {"channel": "book", "symbol": self.symbols,
                                                   "depth": self.depth, "snapshot": True}},
            {"method": "subscribe", "params": {"channel": "ohlc", "symbol": self.symbols,
                                                   "interval": 60, "snapshot": True}},
            {"method": "subscribe", "params": {"channel": "trade", "symbol": self.symbols,
                                                   "snapshot": True}},
        ]

    def handle(self, message: dict) -> None:
        self.last_message = time.time()
        channel = message.get("channel")
        data = message.get("data") or []
        if channel == "ticker":
            for item in data:
                symbol = item["symbol"]
                self.quotes[symbol] = {
                    "last": float(item.get("last") or (item["bid"] + item["ask"]) / 2),
                    "bid": float(item["bid"]), "ask": float(item["ask"]),
                    "timestamp": item["timestamp"], "received_ts": self.last_message,
                    "volume_24h": float(item.get("volume", 0)),
                }
        elif channel == "book":
            for item in data:
                symbol = item["symbol"]
                book = self.books.setdefault(symbol, OrderBook(self.depth))
                if not book.apply(item, snapshot=message.get("type") == "snapshot"):
                    raise ValueError(f"Kraken L2 checksum mismatch for {symbol}")
        elif channel == "ohlc":
            for item in data:
                self.candles.update(item)
        elif channel == "trade":
            for item in data:
                symbol = item["symbol"]
                self.trades.setdefault(symbol, []).append({
                    "price": float(item["price"]), "qty": float(item["qty"]),
                    "side": item["side"], "trade_id": item["trade_id"],
                    "timestamp": item["timestamp"],
                })
                self.trades[symbol] = self.trades[symbol][-100:]

    def snapshot(self) -> dict:
        return {
            "source": "kraken-ws-v2", "received_ts": self.last_message,
            "connected_at": self.connected_at, "error": self.error,
            "quotes": self.quotes,
            "books": {symbol: book.metrics() for symbol, book in self.books.items() if book.valid},
            "candles": {symbol: self.candles.rows(symbol) for symbol in self.symbols},
            "trades": self.trades,
        }

    def write(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temp = self.output.with_suffix(self.output.suffix + ".tmp")
        temp.write_text(json.dumps(self.snapshot(), separators=(",", ":")), encoding="utf-8")
        os.replace(temp, self.output)

    async def run_once(self) -> None:
        async with websockets.connect(URL, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            self.connected_at = time.time()
            self.error = ""
            for request in self.subscriptions():
                await ws.send(json.dumps(request))
            async for raw in ws:
                try:
                    self.handle(json.loads(raw, parse_float=Decimal))
                    self.write()
                except ValueError:
                    raise

    async def run_forever(self) -> None:
        delay = 1
        while True:
            try:
                await self.run_once()
                delay = 1
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.write()
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)


def main() -> None:
    symbols = [s.strip() for s in os.getenv("KRAKEN_WS_SYMBOLS", "BTC/AUD,ETH/AUD,SOL/AUD").split(",") if s.strip()]
    output = os.getenv("KRAKEN_WS_OUTPUT", "state/live/kraken_stream.json")
    asyncio.run(KrakenStream(symbols, output).run_forever())


if __name__ == "__main__":
    main()
