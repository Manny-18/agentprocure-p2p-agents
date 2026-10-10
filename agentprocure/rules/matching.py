"""Accounts-payable controls: 3-way match, duplicate detection and bank-change fraud checks."""
from __future__ import annotations

import re

from .common import days_between, r2


def three_way_match(*, po: dict, grn: dict | None, invoice: dict, tolerance: dict, tax_rate_pct: float) -> dict:
    """Compare PO (price, qty), GRN (accepted qty) and invoice. Pay only for accepted quantity at PO
    price; anything above that is disputed and needs a credit note."""
    exceptions = []
    po_price = po["unit_price"]
    po_qty = po["qty"]
    inv_line = invoice["lines"][0]
    inv_qty, inv_price = inv_line["qty"], inv_line["unit_price"]

    if not grn:
        exceptions.append({"code": "MISSING_GRN", "severity": "BLOCK", "detail": "No goods receipt against this PO"})
        accepted = 0
    else:
        accepted = grn["accepted_qty"]

    price_var_pct = (inv_price - po_price) / po_price * 100
    if price_var_pct > tolerance["price_pct"]:
        exceptions.append({"code": "PRICE_VARIANCE", "severity": "HOLD",
                           "detail": f"Invoice price {inv_price:.2f} vs PO {po_price:.2f} (+{price_var_pct:.2f}%, tolerance {tolerance['price_pct']}%)",
                           "amount": r2((inv_price - po_price) * min(inv_qty, accepted))})
    if inv_qty > accepted:
        exceptions.append({"code": "QTY_EXCEEDS_ACCEPTED", "severity": "HOLD",
                           "detail": f"Invoiced {inv_qty:,} but only {accepted:,} accepted at GRN ({grn.get('rejected_qty', 0) if grn else 0:,} rejected)",
                           "amount": r2((inv_qty - accepted) * inv_price)})
    if inv_qty > po_qty:
        exceptions.append({"code": "QTY_EXCEEDS_PO", "severity": "HOLD", "detail": f"Invoiced {inv_qty:,} vs PO {po_qty:,}"})
    inv_freight = invoice.get("freight") or 0
    po_freight = po.get("freight") or 0
    if inv_freight - po_freight > tolerance["amount_abs"]:
        exceptions.append({"code": "FREIGHT_NOT_AGREED", "severity": "HOLD",
                           "detail": f"Freight billed {inv_freight:,.2f} vs PO {po_freight:,.2f}",
                           "amount": r2(inv_freight - po_freight)})

    payable_qty = min(inv_qty, accepted)
    payable_price = min(inv_price, po_price) if price_var_pct > tolerance["price_pct"] else inv_price
    approved_taxable = r2(payable_qty * payable_price + min(inv_freight, po_freight))
    billed_taxable = r2(inv_qty * inv_price + inv_freight)
    rate = tax_rate_pct / 100
    approved_total = r2(approved_taxable * (1 + rate))
    billed_total = invoice.get("total") or r2(billed_taxable * (1 + rate))
    disputed_taxable = r2(billed_taxable - approved_taxable)
    status = "MATCHED" if not exceptions else ("BLOCKED" if any(e["severity"] == "BLOCK" for e in exceptions) else "EXCEPTION")
    return {"status": status, "exceptions": exceptions, "po_price": po_price, "invoice_price": inv_price,
            "price_variance_pct": round(price_var_pct, 2), "po_qty": po_qty, "accepted_qty": accepted,
            "invoiced_qty": inv_qty, "approved_taxable": approved_taxable, "approved_tax": r2(approved_total - approved_taxable),
            "approved_total": approved_total, "billed_taxable": billed_taxable, "billed_total": r2(billed_total),
            "disputed_taxable": disputed_taxable, "disputed_total": r2(billed_total - approved_total)}


def _norm(no: str) -> str:
    """'INV/26-27/0042' and 'inv-26-27-42' normalise to the same key: INV|26|27|42."""
    tokens = re.findall(r"[A-Z]+|\d+", (no or "").upper())
    return "|".join(t.lstrip("0") or "0" if t.isdigit() else t for t in tokens)


def duplicate_check(invoice: dict, history: list[dict]) -> dict:
    """Exact duplicates (same vendor + normalised invoice number) and probable ones
    (same vendor + same amount within 7 days)."""
    hits = []
    for h in history:
        if h["vendor_id"] != invoice["vendor_id"]:
            continue
        if _norm(h["invoice_no"]) == _norm(invoice["invoice_no"]):
            hits.append({"code": "DUPLICATE_INVOICE", "severity": "BLOCK", "detail": f"Same invoice number already booked ({h['invoice_no']} on {h['date']})"})
        elif abs((h.get("total") or 0) - (invoice.get("total") or 0)) < 1 and abs(days_between(h["date"], invoice["date"])) <= 7:
            hits.append({"code": "PROBABLE_DUPLICATE", "severity": "HOLD", "detail": f"Same amount from same vendor within 7 days ({h['invoice_no']})"})
    return {"checked_against": len([h for h in history if h["vendor_id"] == invoice["vendor_id"]]), "issues": hits}


def bank_change_check(vendor: dict, invoice: dict | None, as_of, cooling_days: int) -> dict:
    """Business-email-compromise control: a recent, unverified bank-detail change is a hard stop."""
    issues = []
    bank = vendor.get("bank", {})
    changed_on = bank.get("changed_on")
    if changed_on:
        age = days_between(changed_on, as_of)
        if age <= cooling_days and not bank.get("change_verified"):
            issues.append({"code": "BANK_CHANGE_UNVERIFIED", "severity": "BLOCK",
                           "detail": f"Bank account changed {age} days ago via {bank.get('change_channel', 'unknown channel')}, no call-back verification"})
    if invoice and invoice.get("bank_account_masked") and invoice["bank_account_masked"] != bank.get("account_masked"):
        issues.append({"code": "BANK_ON_INVOICE_DIFFERS", "severity": "BLOCK",
                       "detail": "Bank account printed on invoice differs from vendor master"})
    return {"issues": issues}
