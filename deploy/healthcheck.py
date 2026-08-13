#!/usr/bin/env python3
"""Container health probes for the long-running VPS services."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def recent_json(path: str, max_age: float) -> dict:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        modified = source.stat().st_mtime
    except (OSError, ValueError, TypeError) as exc:
        fail(f"unreadable health snapshot: {exc}")
    timestamp = float(payload.get("received_ts") or payload.get("ts") or modified)
    age = max(0.0, time.time() - timestamp)
    if age > max_age:
        fail(f"stale health snapshot: {age:.1f}s > {max_age:.1f}s")
    return payload


def check_fleet(path: str, max_age: float) -> None:
    payload = recent_json(path, max_age)
    if payload.get("halted") and payload.get("positions"):
        fail("halted fleet still reports open positions")


def check_stream(path: str, max_age: float) -> None:
    payload = recent_json(path, max_age)
    if payload.get("error"):
        fail(f"Kraken stream error: {payload['error']}")
    expected = {
        item.strip() for item in os.getenv(
            "KRAKEN_WS_SYMBOLS", "BTC/AUD,ETH/AUD,SOL/AUD"
        ).split(",") if item.strip()
    }
    quotes = payload.get("quotes", {})
    books = payload.get("books", {})
    missing = sorted(symbol for symbol in expected if symbol not in quotes)
    invalid = sorted(
        symbol for symbol in expected
        if books.get(symbol, {}).get("checksum_valid") is not True
    )
    if missing or invalid:
        fail(f"stream incomplete; missing_quotes={missing}, invalid_books={invalid}")


def check_database(max_age: float) -> None:
    import psycopg

    try:
        with psycopg.connect(os.getenv("DATABASE_URL", ""), connect_timeout=4) as conn:
            row = conn.execute(
                "SELECT EXTRACT(EPOCH FROM NOW() - MAX(observed_at)) "
                "FROM fleet_snapshots"
            ).fetchone()
    except psycopg.Error as exc:
        fail(f"snapshot database unavailable: {exc}")
    age = float(row[0]) if row and row[0] is not None else float("inf")
    if age > max_age:
        fail(f"database snapshot stale: {age:.1f}s > {max_age:.1f}s")


def check_http(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                fail(f"health endpoint returned HTTP {response.status}")
    except OSError as exc:
        fail(f"health endpoint unavailable: {exc}")


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: healthcheck.py fleet|stream|database|http [target] [max-age]")
    kind = sys.argv[1]
    if kind in {"fleet", "stream"}:
        if len(sys.argv) != 4:
            fail(f"{kind} requires path and max-age")
        checker = check_fleet if kind == "fleet" else check_stream
        checker(sys.argv[2], float(sys.argv[3]))
    elif kind == "database":
        check_database(float(sys.argv[2]) if len(sys.argv) > 2 else 180.0)
    elif kind == "http":
        check_http(sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000/healthz")
    else:
        fail(f"unknown healthcheck kind: {kind}")


if __name__ == "__main__":
    main()
