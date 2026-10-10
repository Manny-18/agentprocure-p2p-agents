"""Treasury / working-capital expertise: due dates, early-payment discounts and payment priority."""
from __future__ import annotations

from .common import add_days, days_between, r2, to_date
from .msme import disallowance_exposure, msme_due_date, msme_interest


def discount_apr(pct: float, discount_days: int, net_days: int) -> float:
    """Annualised return of taking a cash discount: (d / (1-d)) x 365 / (net - discount days)."""
    d = pct / 100
    return round(d / (1 - d) * 365 / (net_days - discount_days) * 100, 2)


def plan_invoice_payment(*, invoice: dict, payable: float, vendor: dict, acceptance_date, company: dict) -> dict:
    """Recommend when to pay one approved invoice and why."""
    as_of = company["as_of"]
    terms = vendor["terms"]
    contractual_due = add_days(invoice["date"], terms["payment_days"])
    msme = msme_due_date(acceptance_date=acceptance_date, category=vendor["msme"]["category"],
                         written_agreement=terms["written_agreement"], agreed_days=terms["payment_days"])
    due = contractual_due
    reasons = [f"Contract terms: {terms['payment_days']} days from invoice date -> {contractual_due.isoformat()}"]
    if msme["covered"]:
        msme_due = to_date(msme["due_date"])
        if msme_due < due:
            due = msme_due
        reasons.append(f"MSMED Act s.15 ({vendor['msme']['category']} enterprise): {msme['basis']} -> pay by {msme['due_date']}")

    pay_on, take_discount, disc = due, False, None
    if terms.get("discount"):
        dterms = terms["discount"]
        apr = discount_apr(dterms["pct"], dterms["days"], terms["payment_days"])
        last_day = add_days(invoice["date"], dterms["days"])
        still_open = to_date(as_of) <= last_day
        take_discount = still_open and apr > company["cost_of_funds_pct"]
        disc = {"terms": f"{dterms['pct']}% if paid within {dterms['days']} days, else net {terms['payment_days']}",
                "annualised_return_pct": apr, "cost_of_funds_pct": company["cost_of_funds_pct"],
                "window_closes": last_day.isoformat(), "window_open": still_open,
                "amount": r2(payable * dterms["pct"] / 100), "take": take_discount}
        if take_discount:
            pay_on = last_day
            reasons.append(f"Take the {dterms['pct']}% discount: {apr}% annualised beats {company['cost_of_funds_pct']}% cost of funds")
        else:
            why = "window closed" if not still_open else f"{apr}% annualised is below the {company['cost_of_funds_pct']}% cost of funds"
            reasons.append(f"Skip the early-payment discount ({why}); hold cash until the due date")
    if to_date(pay_on) < to_date(as_of):
        pay_on = to_date(as_of)
    return {"invoice_no": invoice["invoice_no"], "payable": r2(payable), "due_date": due.isoformat(),
            "pay_on": to_date(pay_on).isoformat(), "msme": msme, "discount": disc, "take_discount": take_discount,
            "days_until_due": days_between(as_of, due), "reasons": reasons,
            "itc_reversal_deadline": add_days(invoice["date"], 180).isoformat()}


def review_open_payables(*, open_items: list[dict], vendor: dict, company: dict) -> list[dict]:
    """Scan other unpaid invoices of the same vendor for MSMED / s.37(2)(g) exposure."""
    alerts = []
    for item in open_items:
        msme = msme_due_date(acceptance_date=item["accepted_date"], category=vendor["msme"]["category"],
                             written_agreement=vendor["terms"]["written_agreement"], agreed_days=vendor["terms"]["payment_days"])
        if not msme["covered"]:
            continue
        overdue_days = days_between(msme["due_date"], company["as_of"])
        interest = msme_interest(principal=item["total"], due_date=msme["due_date"], as_of=company["as_of"],
                                 bank_rate_pct=company["rbi_bank_rate_pct"])
        exposure = disallowance_exposure(amount=item["taxable"], due_date=msme["due_date"],
                                         tax_year_end=company["tax_year_end"], paid=False)
        alerts.append({"invoice_no": item["invoice_no"], "total": item["total"], "status": item.get("status"),
                       "msme_due": msme["due_date"], "overdue_days": max(0, overdue_days), "days_to_due": max(0, -overdue_days),
                       "severity": "CRITICAL" if overdue_days > 0 else ("HIGH" if overdue_days >= -7 else "INFO"),
                       "interest_accrued": interest["interest"], "interest_rate_pct": interest["annual_rate_pct"],
                       "interest_tax_deductible": False, "disallowance_if_unpaid_at_year_end": exposure["amount_at_risk"],
                       "action": "Pay in the next payment run with statutory interest; fix the approval bottleneck"
                       if overdue_days > 0 else "Schedule before the MSME due date"})
    return alerts
