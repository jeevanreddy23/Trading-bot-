from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


DATABASE_URL = os.getenv("DATABASE_URL", "")
STATE_PATH = Path(os.getenv("FLEET_STATE_PATH", "/app/state/live/state.json"))
POLL_SECONDS = max(2, int(os.getenv("COLLECTOR_POLL_SECONDS", "15")))


def initialise(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_snapshots (
            id BIGSERIAL PRIMARY KEY,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_mtime DOUBLE PRECISION NOT NULL UNIQUE,
            payload JSONB NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS fleet_snapshots_observed_at_idx "
        "ON fleet_snapshots (observed_at DESC)"
    )
    conn.commit()


def json_safe(value):
    """PostgreSQL JSONB rejects NaN/Infinity, which old state files may contain."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def collect_once(conn: psycopg.Connection, last_mtime: float | None) -> float | None:
    try:
        mtime = STATE_PATH.stat().st_mtime
    except FileNotFoundError:
        return last_mtime
    if mtime == last_mtime:
        return last_mtime

    payload = json_safe(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    conn.execute(
        """
        INSERT INTO fleet_snapshots (source_mtime, payload)
        VALUES (%s, %s)
        ON CONFLICT (source_mtime) DO NOTHING
        """,
        (mtime, Jsonb(payload)),
    )
    conn.execute(
        "DELETE FROM fleet_snapshots WHERE observed_at < NOW() - INTERVAL '30 days'"
    )
    conn.commit()
    return mtime


def main() -> None:
    last_mtime: float | None = None
    while True:
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                initialise(conn)
                while True:
                    last_mtime = collect_once(conn, last_mtime)
                    time.sleep(POLL_SECONDS)
        except (OSError, psycopg.Error, json.JSONDecodeError) as exc:
            print(f"[collector] retrying after error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
