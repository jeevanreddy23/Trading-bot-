from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fill:
    ok: bool
    px: float = 0.0
    qty: float = 0.0
    fee_aud: float = 0.0
    info: str = ""


class Executor:
    mode = "paper"

    def execute(self, sig, qty: float, ctx) -> Fill:
        raise NotImplementedError
