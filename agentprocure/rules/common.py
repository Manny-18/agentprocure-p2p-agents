"""Shared helpers: dates, rounding and Indian-style money formatting."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal


def to_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def add_days(d, days: int) -> date:
    return to_date(d) + timedelta(days=days)


def days_between(start, end) -> int:
    return (to_date(end) - to_date(start)).days


def r2(x: float) -> float:
    """Round half-up to 2 decimals (paise), the way invoices are rounded."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r0(x: float) -> int:
    """Round half-up to whole rupees (TDS is rounded to the nearest rupee)."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def inr(x: float | int | None, decimals: int | None = None) -> str:
    """Format a number the Indian way: 1774000 -> 'Rs 17,74,000'."""
    if x is None:
        return "-"
    neg = x < 0
    x = abs(x)
    if decimals is None:
        decimals = 0 if float(x).is_integer() else 2
    whole, _, frac = f"{x:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    out = f"Rs {whole}" + (f".{frac}" if frac else "")
    return f"-{out}" if neg else out


def lakh(x: float) -> str:
    return f"Rs {x / 100000:.2f} lakh"


def crore(x: float) -> str:
    return f"Rs {x / 10000000:.2f} crore"
