from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "postgresql://unused")
os.environ.setdefault("MONITOR_TOKEN", "test-token-that-is-at-least-24-characters")

from fastapi import HTTPException

from monitor.api import require_token
from monitor.collector import json_safe


def main() -> None:
    cleaned = json_safe({"nan": math.nan, "nested": [math.inf, 1.0]})
    assert cleaned == {"nan": None, "nested": [None, 1.0]}

    require_token(f"Bearer {os.environ['MONITOR_TOKEN']}")
    try:
        require_token("Bearer wrong")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("invalid monitoring token was accepted")

    print("2/2 monitoring checks passed")


if __name__ == "__main__":
    main()
