"""MSMED Act, 2006 (Chapter V) and the income-tax disallowance for late payment to MSEs.

* s.15: pay a micro/small supplier by the agreed date (written agreement, never more than 45 days
  from acceptance) or, with no written agreement, within 15 days of acceptance.
* s.16: if late, compound interest with monthly rests at 3x the Bank Rate notified by RBI,
  whatever the contract says; s.23: that interest is not tax-deductible.
* Income-tax Act 2025 s.37(2)(g) (formerly s.43B(h) of the 1961 Act): an amount owed to a
  micro/small enterprise and unpaid beyond the s.15 limit is deductible only in the year paid.
* Medium enterprises and traders are outside Chapter V.
"""
from __future__ import annotations

from .common import add_days, days_between, r2, to_date

COVERED = {"micro", "small"}
MAX_AGREED_DAYS = 45
NO_AGREEMENT_DAYS = 15


def msme_due_date(*, acceptance_date, category: str | None, written_agreement: bool, agreed_days: int) -> dict:
    if (category or "").lower() not in COVERED:
        return {"covered": False, "due_date": None, "days_allowed": None,
                "basis": f"Supplier category '{category}' is outside MSMED Act Chapter V (only micro/small enterprises)"}
    days = min(agreed_days, MAX_AGREED_DAYS) if written_agreement else NO_AGREEMENT_DAYS
    basis = (f"Written agreement of {agreed_days} days, capped at {MAX_AGREED_DAYS}" if written_agreement
             else f"No written agreement: {NO_AGREEMENT_DAYS} days from acceptance")
    return {"covered": True, "due_date": add_days(acceptance_date, days).isoformat(), "days_allowed": days, "basis": basis}


def msme_interest(*, principal: float, due_date, as_of, bank_rate_pct: float) -> dict:
    """Compound interest with monthly rests at 3x Bank Rate for the days past due."""
    annual = 3 * bank_rate_pct / 100
    late_days = max(0, days_between(due_date, as_of))
    months = late_days / (365 / 12)
    interest = principal * ((1 + annual / 12) ** months - 1) if late_days else 0.0
    return {"annual_rate_pct": round(annual * 100, 2), "late_days": late_days, "interest": r2(interest),
            "tax_deductible": False,
            "note": "Computed at the current Bank Rate; a formal claim applies the rate notified for each month."}


def disallowance_exposure(*, amount: float, due_date, tax_year_end, paid: bool) -> dict:
    """If an MSE due is past its s.15 date and still unpaid at year end, the expense is
    disallowed for that tax year (Income-tax Act 2025 s.37(2)(g))."""
    due = to_date(due_date)
    at_risk = (not paid) and due <= to_date(tax_year_end)
    return {"provision": "Income-tax Act 2025 s.37(2)(g) (formerly s.43B(h))", "amount_at_risk": r2(amount) if at_risk else 0.0,
            "deadline_to_cure": to_date(tax_year_end).isoformat(), "at_risk": at_risk}
