from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")


def now_syd() -> datetime:
    return datetime.now(SYD)


def syd_date() -> str:
    return now_syd().strftime("%Y-%m-%d")


def market_of(symbol: str) -> str:
    if "/" in symbol:
        return "crypto"
    if symbol.endswith("=F"):
        return "commodities"
    if symbol.endswith("=X"):
        return "fx"
    return "stocks"


def quote_ccy(symbol: str) -> str:
    """Currency the instrument's P&L accrues in."""
    if symbol.endswith(".AX"):
        return "AUD"
    if symbol.endswith("=X"):           # AUDUSD=X -> USD, USDJPY=X -> JPY
        return symbol[3:6]
    if "/" in symbol:                   # BTC/USDT -> treat stables as USD
        q = symbol.split("/")[1]
        return "USD" if q in ("USDT", "USDC", "USD") else q
    return "USD"                        # US stocks, futures


def market_open(symbol: str) -> bool:
    """Rough live-trading gate. Paper mode marks fills instead of blocking."""
    m = market_of(symbol)
    if m == "crypto":
        return True
    now = now_syd()
    if m in ("fx", "commodities"):
        # closed Sydney Saturday 08:00 -> Monday 08:00 (approximates the global weekend gap)
        wd, hr = now.weekday(), now.hour
        if wd == 5 and hr >= 8:
            return False
        if wd == 6:
            return False
        if wd == 0 and hr < 8:
            return False
        return True
    # stocks
    if symbol.endswith(".AX"):
        return now.weekday() < 5 and (10, 0) <= (now.hour, now.minute) <= (16, 0)
    ny = datetime.now(NY)
    if ny.weekday() >= 5:
        return False
    mins = ny.hour * 60 + ny.minute
    return 9 * 60 + 30 <= mins <= 16 * 60
