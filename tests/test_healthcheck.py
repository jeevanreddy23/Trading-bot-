#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deploy.healthcheck import check_fleet, check_stream


def expect_failure(fn, message: str) -> None:
    try:
        fn()
    except SystemExit:
        return
    raise AssertionError(message)


def main() -> None:
    now = time.time()
    with tempfile.TemporaryDirectory() as folder:
        fleet_path = Path(folder) / "state.json"
        fleet_path.write_text(json.dumps({"ts": now, "halted": False}), encoding="utf-8")
        check_fleet(str(fleet_path), 180)
        fleet_path.write_text(json.dumps({"ts": now - 500}), encoding="utf-8")
        expect_failure(lambda: check_fleet(str(fleet_path), 180), "stale fleet passed")

        stream_path = Path(folder) / "kraken_stream.json"
        symbols = ["BTC/AUD", "ETH/AUD", "SOL/AUD"]
        stream_path.write_text(json.dumps({
            "received_ts": now,
            "error": "",
            "quotes": {symbol: {"last": 1} for symbol in symbols},
            "books": {symbol: {"checksum_valid": True} for symbol in symbols},
        }), encoding="utf-8")
        check_stream(str(stream_path), 90)
        broken = json.loads(stream_path.read_text(encoding="utf-8"))
        broken["books"]["BTC/AUD"]["checksum_valid"] = False
        stream_path.write_text(json.dumps(broken), encoding="utf-8")
        expect_failure(lambda: check_stream(str(stream_path), 90), "bad checksum passed")

    print("4/4 container health checks passed")


if __name__ == "__main__":
    main()
