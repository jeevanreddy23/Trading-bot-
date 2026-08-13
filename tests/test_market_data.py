#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet.market_data.kraken_ws import KrakenStream
from fleet.market_data.orderbook import OrderBook


def test_book_checksum():
    book = OrderBook(10)
    payload = {
        "bids": [
            {"price": "45283.5", "qty": "0.10000000"}, {"price": "45283.4", "qty": "1.54582015"},
            {"price": "45282.1", "qty": "0.10000000"}, {"price": "45281.0", "qty": "0.10000000"},
            {"price": "45280.3", "qty": "1.54592586"}, {"price": "45279.0", "qty": "0.07990000"},
            {"price": "45277.6", "qty": "0.03310103"}, {"price": "45277.5", "qty": "0.30000000"},
            {"price": "45277.3", "qty": "1.54602737"}, {"price": "45276.6", "qty": "0.15445238"},
        ],
        "asks": [
            {"price": "45285.2", "qty": "0.00100000"}, {"price": "45286.4", "qty": "1.54571953"},
            {"price": "45286.6", "qty": "1.54571109"}, {"price": "45289.6", "qty": "1.54560911"},
            {"price": "45290.2", "qty": "0.15890660"}, {"price": "45291.8", "qty": "1.54553491"},
            {"price": "45294.7", "qty": "0.04454749"}, {"price": "45296.1", "qty": "0.35380000"},
            {"price": "45297.5", "qty": "0.09945542"}, {"price": "45299.5", "qty": "0.18772827"},
        ],
        "checksum": 3310070434,
    }
    assert book.apply(payload, snapshot=True)
    assert book.checksum() == 3310070434
    assert book.metrics()["spread_pct"] > 0


def test_stream_parses_public_channels(tmp_path):
    stream = KrakenStream(["BTC/AUD"], str(tmp_path / "stream.json"))
    stream.handle({"channel": "ticker", "type": "snapshot", "data": [{
        "symbol": "BTC/AUD", "last": Decimal("103420"), "bid": Decimal("103400"),
        "ask": Decimal("103440"), "timestamp": "2026-08-11T08:00:00Z", "volume": Decimal("12.3"),
    }]})
    stream.handle({"channel": "ohlc", "type": "update", "data": [{
        "symbol": "BTC/AUD", "open": Decimal("103000"), "high": Decimal("104000"),
        "low": Decimal("102900"), "close": Decimal("103420"), "volume": Decimal("2.4"),
        "interval_begin": "2026-08-11T08:00:00Z", "interval": 60,
    }]})
    stream.handle({"channel": "trade", "type": "update", "data": [{
        "symbol": "BTC/AUD", "price": Decimal("103420"), "qty": Decimal("0.01"),
        "side": "buy", "trade_id": 99, "timestamp": "2026-08-11T08:01:00Z",
    }]})
    snap = stream.snapshot()
    assert snap["quotes"]["BTC/AUD"]["bid"] == 103400.0
    assert snap["candles"]["BTC/AUD"][0]["close"] == 103420.0
    assert snap["trades"]["BTC/AUD"][0]["trade_id"] == 99


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    test_book_checksum()
    with tempfile.TemporaryDirectory() as path:
        test_stream_parses_public_channels(Path(path))
    print("2/2 market-data checks passed")
