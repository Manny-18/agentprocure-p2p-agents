"""GST expertise as deterministic, testable functions.

Covers: GSTIN structure and checksum, PAN consistency, intra- vs inter-state tax
(CGST+SGST vs IGST), invoice tax arithmetic against the HSN rate, e-invoice (IRN)
applicability and the 30-day IRP reporting window, and input-tax-credit readiness.
"""
from __future__ import annotations

import re

from .common import days_between, r2

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory",
}

# E-invoicing: mandatory where the supplier's aggregate annual turnover crossed Rs 5 crore in any
# FY since 2017-18 (in force since 1 Aug 2023). Suppliers with AATO >= Rs 10 crore must report to
# the IRP within 30 days of the invoice date (since 1 Apr 2025).
EINVOICE_AATO_CR = 5
IRP_30DAY_AATO_CR = 10
IRP_REPORTING_DAYS = 30
ITC_PAYMENT_DAYS = 180  # CGST s.16(2) second proviso: pay the supplier within 180 days or reverse ITC


def gstin_checksum(first14: str) -> str:
    """Luhn mod-36 check character used by GSTN."""
    factor, total = 2, 0
    for ch in reversed(first14):
        addend = factor * GSTIN_CHARS.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // 36 + addend % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def validate_gstin(gstin: str | None, expected_pan: str | None = None) -> dict:
    """Return a structured verdict on a GSTIN (format, state, checksum, PAN match)."""
    result = {"gstin": gstin, "format_ok": False, "checksum_ok": False, "state_code": None,
              "state": None, "pan_in_gstin": None, "pan_match": None, "issues": []}
    if not gstin:
        result["issues"].append({"code": "GSTIN_MISSING", "severity": "BLOCK", "detail": "No GSTIN on record"})
        return result
    g = gstin.strip().upper()
    result["format_ok"] = bool(GSTIN_RE.match(g))
    if not result["format_ok"]:
        result["issues"].append({"code": "GSTIN_FORMAT_INVALID", "severity": "BLOCK",
                                 "detail": f"{g} does not follow the 15-character GSTIN pattern"})
        return result
    result["state_code"] = g[:2]
    result["state"] = STATE_CODES.get(g[:2])
    result["pan_in_gstin"] = g[2:12]
    if result["state"] is None:
        result["issues"].append({"code": "GSTIN_STATE_INVALID", "severity": "BLOCK",
                                 "detail": f"State code {g[:2]} is not a valid GST state code"})
    expected = gstin_checksum(g[:14])
    result["checksum_ok"] = expected == g[14]
    if not result["checksum_ok"]:
        result["issues"].append({"code": "GSTIN_CHECKSUM_INVALID", "severity": "BLOCK",
                                 "detail": f"Check digit is '{g[14]}', expected '{expected}': GSTIN is mistyped or fabricated"})
    if expected_pan:
        result["pan_match"] = result["pan_in_gstin"] == expected_pan.upper()
        if not result["pan_match"]:
            result["issues"].append({"code": "PAN_MISMATCH", "severity": "BLOCK",
                                     "detail": f"PAN inside GSTIN ({result['pan_in_gstin']}) differs from vendor-master PAN ({expected_pan})"})
    return result


def tax_type(supplier_state: str, place_of_supply: str) -> str:
    """Intra-state supply -> CGST+SGST; inter-state -> IGST (IGST Act s.7/8)."""
    return "CGST+SGST" if supplier_state == place_of_supply else "IGST"


def compute_tax(taxable: float, rate_pct: float, supplier_state: str, place_of_supply: str) -> dict:
    kind = tax_type(supplier_state, place_of_supply)
    if kind == "IGST":
        igst = r2(taxable * rate_pct / 100)
        cgst = sgst = 0.0
    else:
        cgst = sgst = r2(taxable * rate_pct / 200)
        igst = 0.0
    return {"tax_type": kind, "rate_pct": rate_pct, "taxable": r2(taxable), "cgst": cgst, "sgst": sgst,
            "igst": igst, "tax_total": r2(cgst + sgst + igst), "invoice_total": r2(taxable + cgst + sgst + igst)}


def invoice_taxable(invoice: dict) -> float:
    lines = sum(l["qty"] * l["unit_price"] for l in invoice["lines"])
    return r2(lines + (invoice.get("freight") or 0))


def check_invoice_tax(invoice: dict, vendor: dict, company: dict, hsn_rates: dict) -> dict:
    """Validate the GST on a supplier invoice. Freight billed by the supplier follows the goods rate."""
    issues = []
    gstin_check = validate_gstin(invoice.get("supplier_gstin"), vendor.get("pan"))
    issues += gstin_check["issues"]
    if invoice.get("supplier_gstin") != vendor.get("gstin"):
        issues.append({"code": "GSTIN_NOT_ON_MASTER", "severity": "BLOCK",
                       "detail": "Invoice GSTIN differs from the GSTIN in the vendor master"})
    if invoice.get("buyer_gstin") != company["gstin"]:
        issues.append({"code": "BUYER_GSTIN_WRONG", "severity": "BLOCK",
                       "detail": "Invoice is not addressed to our GSTIN; ITC cannot be claimed"})

    rates = {hsn_rates[l["hsn"]]["rate"] for l in invoice["lines"] if l["hsn"] in hsn_rates}
    unknown = [l["hsn"] for l in invoice["lines"] if l["hsn"] not in hsn_rates]
    if unknown:
        issues.append({"code": "HSN_UNKNOWN", "severity": "WARN", "detail": f"No rate on file for HSN {unknown}"})
    rate = max(rates) if rates else 18
    taxable = invoice_taxable(invoice)
    supplier_state = (invoice.get("supplier_gstin") or vendor["gstin"])[:2]
    expected = compute_tax(taxable, rate, supplier_state, invoice["place_of_supply"])

    billed = {"cgst": invoice.get("cgst", 0) or 0, "sgst": invoice.get("sgst", 0) or 0, "igst": invoice.get("igst", 0) or 0}
    if expected["tax_type"] == "IGST" and (billed["cgst"] or billed["sgst"]):
        issues.append({"code": "WRONG_TAX_TYPE", "severity": "BLOCK",
                       "detail": "Inter-state supply billed with CGST+SGST; IGST is required"})
    if expected["tax_type"] == "CGST+SGST" and billed["igst"]:
        issues.append({"code": "WRONG_TAX_TYPE", "severity": "BLOCK",
                       "detail": "Intra-state supply billed with IGST; CGST+SGST is required"})
    for k in ("cgst", "sgst", "igst"):
        if abs(billed[k] - expected[k]) > 1.0:
            issues.append({"code": "TAX_AMOUNT_MISMATCH", "severity": "HOLD",
                           "detail": f"{k.upper()} billed {billed[k]:.2f}, expected {expected[k]:.2f} at {rate}%"})
    billed_total = invoice.get("total") or 0
    if abs(billed_total - expected["invoice_total"]) > 1.0:
        issues.append({"code": "TOTAL_MISMATCH", "severity": "HOLD",
                       "detail": f"Invoice total {billed_total:.2f} vs recomputed {expected['invoice_total']:.2f}"})
    return {"gstin": gstin_check, "expected": expected, "billed": billed, "issues": issues}


def einvoice_check(invoice: dict, vendor: dict) -> dict:
    aato = vendor.get("aato_cr", 0) or 0
    required = aato > EINVOICE_AATO_CR
    issues = []
    lag = None
    if required and not invoice.get("irn"):
        issues.append({"code": "IRN_MISSING", "severity": "BLOCK",
                       "detail": f"Supplier AATO Rs {aato} cr > Rs {EINVOICE_AATO_CR} cr: invoice without IRN is not a valid tax invoice; ITC at risk"})
    if required and invoice.get("irn") and invoice.get("irn_date"):
        lag = days_between(invoice["date"], invoice["irn_date"])
        if aato >= IRP_30DAY_AATO_CR and lag > IRP_REPORTING_DAYS:
            issues.append({"code": "IRN_LATE", "severity": "BLOCK",
                           "detail": f"IRN generated {lag} days after invoice date; IRP limit is {IRP_REPORTING_DAYS} days for AATO >= Rs {IRP_30DAY_AATO_CR} cr"})
    return {"required": required, "supplier_aato_cr": aato, "irn_present": bool(invoice.get("irn")),
            "irn_lag_days": lag, "issues": issues}


def itc_readiness(invoice: dict, grn: dict | None, tax_issues: list[dict]) -> dict:
    """Conditions of CGST s.16(2) in simplified form."""
    checks = {
        "valid_tax_invoice": not any(i["severity"] == "BLOCK" for i in tax_issues),
        "goods_received": bool(grn and grn.get("accepted_qty", 0) > 0),
        "reflected_in_gstr2b": bool(invoice.get("in_gstr2b")),
    }
    return {"eligible_now": all(checks.values()), "checks": checks,
            "pay_within_days": ITC_PAYMENT_DAYS,
            "note": "ITC must be reversed if the supplier is not paid within 180 days of the invoice date."}
