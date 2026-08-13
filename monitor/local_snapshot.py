from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def write_local_snapshot(state_path: str, out_path: str) -> None:
    """Write a script-readable snapshot so public/index.html also works via file://."""
    source = Path(state_path)
    if not source.exists():
        return
    state = json.loads(source.read_text(encoding="utf-8"), parse_constant=lambda _: None)
    observed = datetime.fromtimestamp(float(state.get("ts", 0)), UTC).isoformat()
    payload = {
        "status": "local",
        "observed_at": observed,
        "age_seconds": 0,
        "fleet": state,
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(f"window.__FLEET_SNAPSHOT__={encoded};\n", encoding="utf-8")
    os.replace(temp, target)
