from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

import psycopg
from fastapi import FastAPI, Header, HTTPException, Response, status


DATABASE_URL = os.getenv("DATABASE_URL", "")
MONITOR_TOKEN = os.environ["MONITOR_TOKEN"]
if len(MONITOR_TOKEN) < 24:
    raise RuntimeError("MONITOR_TOKEN must contain at least 24 characters")

app = FastAPI(title="Fleet Monitor", docs_url=None, redoc_url=None)


def require_token(authorization: str | None) -> None:
    expected = f"Bearer {MONITOR_TOKEN}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/v1/status")
def fleet_status(
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict:
    require_token(authorization)
    response.headers["Cache-Control"] = "no-store"
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=4) as conn:
            row = conn.execute(
                """
                SELECT observed_at, payload
                FROM fleet_snapshots
                ORDER BY observed_at DESC
                LIMIT 1
                """
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="monitor database unavailable") from exc

    if row is None:
        raise HTTPException(status_code=503, detail="waiting for first fleet snapshot")

    observed_at, payload = row
    age_seconds = max(0, (datetime.now(UTC) - observed_at).total_seconds())
    return {
        "status": "ok" if age_seconds <= 90 else "stale",
        "observed_at": observed_at.isoformat(),
        "age_seconds": round(age_seconds, 1),
        "fleet": payload,
    }
