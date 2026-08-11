from __future__ import annotations

import os

import yaml

DEF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def load_config(path: str | None = None) -> dict:
    with open(path or DEF_PATH) as f:
        return yaml.safe_load(f)


def dig(cfg: dict, path: str, default=None):
    cur = cfg
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
