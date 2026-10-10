"""Procurement policy: delegation of authority, competitive quotes, split purchases, budget,
single-source justification and vendor due diligence."""
from __future__ import annotations

from .common import days_between, inr
from .gst import validate_gstin
from .matching import bank_change_check

PO_PROCESSING_DAYS = 2  # typical PR-to-PO time, used for lead-time feasibility
WEAK_JUSTIFICATION_HINTS = ("familiar", "urgent", "already", "known", "fast", "convenient")


def _band(table: list[dict], amount: float) -> dict:
    for row in table:
        if row["max"] is None or amount <= row["max"]:
            return row
    return table[-1]


def approver_for(amount: float, doa: list[dict]) -> str:
    return _band(doa, amount)["approver"]


def escalate_one_level(approver: str, doa: list[dict]) -> str:
    names = [r["approver"] for r in doa]
    i = names.index(approver)
    return names[min(i + 1, len(names) - 1)]


def higher_of(a: str, b: str, doa: list[dict]) -> str:
    names = [r["approver"] for r in doa]
    return a if names.index(a) >= names.index(b) else b


def quote_rule(amount: float, rules: list[dict]) -> dict:
    return _band(rules, amount)


def budget_check(cost_center: str, amount: float, budgets: dict, pending_same_cc: float = 0.0) -> dict:
    b = budgets.get(cost_center)
    if not b:
        return {"ok": False, "remaining": 0, "issues": [{"code": "COST_CENTER_UNKNOWN", "severity": "BLOCK", "detail": cost_center}]}
    remaining = b["fy_budget"] - b["consumed"] - b["committed"]
    issues = []
    if amount > remaining:
        issues.append({"code": "BUDGET_EXCEEDED", "severity": "BLOCK",
                       "detail": f"{inr(amount)} exceeds remaining budget {inr(remaining)} on {cost_center}"})
    elif amount + pending_same_cc > remaining:
        issues.append({"code": "BUDGET_AT_RISK", "severity": "WARN",
                       "detail": f"With pending requisitions ({inr(pending_same_cc)}) the cost center would need {inr(amount + pending_same_cc)} vs {inr(remaining)} remaining"})
    return {"ok": not issues, "cost_center": cost_center, "name": b["name"], "remaining": remaining, "issues": issues}


def split_purchase_check(pr: dict, history: list[dict], vendor_id: str | None, window_days: int, quote_rules: list[dict]) -> dict:
    """Flag requisitions that look like one purchase cut into pieces to stay under a threshold."""
    related = [h for h in history
               if abs(days_between(h["date"], pr["date"])) <= window_days
               and h.get("status") != "cancelled"
               and (h.get("requester") == pr["requester"] or h.get("cost_center") == pr["cost_center"])
               and (h.get("vendor_id") == vendor_id or h.get("category") == pr["category"])]
    combined = pr["estimated_value"] + sum(h["value"] for h in related)
    single_band = quote_rule(pr["estimated_value"], quote_rules)
    combined_band = quote_rule(combined, quote_rules)
    issues = []
    if related and (combined_band is not single_band):
        issues.append({"code": "SPLIT_PURCHASE_SUSPECTED", "severity": "BLOCK",
                       "detail": (f"{len(related)} related PR(s) within {window_days} days; combined value {inr(combined)} "
                                  f"falls in a stricter band (min {combined_band['min_quotes']} quotes"
                                  f"{', competitive RFQ' if combined_band.get('rfq_required') else ''})")})
    return {"related": related, "combined_value": combined, "issues": issues}


def vendor_due_diligence(vendor: dict, as_of, cooling_days: int) -> dict:
    g = validate_gstin(vendor.get("gstin"), vendor.get("pan"))
    issues = list(g["issues"])
    if vendor.get("gst_status") != "Active":
        issues.append({"code": "GST_REGISTRATION_INACTIVE", "severity": "BLOCK", "detail": f"GST status: {vendor.get('gst_status')}"})
    if not vendor.get("approved"):
        issues.append({"code": "VENDOR_NOT_APPROVED", "severity": "BLOCK", "detail": "Vendor not on approved vendor list"})
    issues += bank_change_check(vendor, None, as_of, cooling_days)["issues"]
    if not vendor.get("pan"):
        issues.append({"code": "PAN_NOT_ON_MASTER", "severity": "WARN",
                       "detail": "No PAN on vendor master: TDS on goods applies at the higher 5% rate until PAN is furnished"})
    blocking = [i for i in issues if i["severity"] == "BLOCK"]
    return {"vendor": vendor["name"], "gstin": g, "issues": issues, "clean": not blocking}


def check_requisition(pr: dict, quotes: list[dict], vendors: dict, company: dict, history: list[dict]) -> dict:
    """Run every policy control on a requisition and return findings with severities.
    BLOCK = cannot proceed; WARN = proceed but tell the approver."""
    findings: list[dict] = []
    value = pr["estimated_value"]
    approver = approver_for(value, company["doa"])
    rule = quote_rule(value, company["quote_rules"])

    valid_quotes = [q for q in quotes if q["vendor_id"] in vendors]
    sole_source_ok = False
    if pr.get("single_source"):
        just = (pr.get("justification") or "").lower()
        weak = (not just) or any(h in just for h in WEAK_JUSTIFICATION_HINTS)
        sole_source_ok = not weak
        findings.append({"code": "SINGLE_SOURCE" if sole_source_ok else "SINGLE_SOURCE_WEAK_JUSTIFICATION",
                         "severity": "WARN",
                         "detail": "Sole-source request with documented justification; one extra approval level" if sole_source_ok
                         else "Sole-source request; justification does not cite OEM lock-in, IP or a documented capability gap"})
        approver = escalate_one_level(approver, company["doa"])
    if len(valid_quotes) < rule["min_quotes"]:
        findings.append({"code": "QUOTES_INSUFFICIENT", "severity": "WARN" if sole_source_ok else "BLOCK",
                         "detail": f"{len(valid_quotes)} quote(s) received; policy needs {rule['min_quotes']} for {inr(value)}"})
    if rule.get("rfq_required"):
        findings.append({"code": "RFQ_REQUIRED", "severity": "WARN", "detail": "Value above Rs 25 lakh: run a formal RFQ / e-auction"})

    pending = sum(h["value"] for h in history if h.get("cost_center") == pr["cost_center"] and h.get("status") == "pending approval")
    budget = budget_check(pr["cost_center"], value, company["budgets"], pending)
    findings += budget["issues"]

    quote_vendor = quotes[0]["vendor_id"] if len(quotes) == 1 else None
    split = split_purchase_check(pr, history, quote_vendor, company["split_window_days"], company["quote_rules"])
    findings += split["issues"]
    if split["issues"]:
        approver = higher_of(approver, approver_for(split["combined_value"], company["doa"]), company["doa"])

    diligence = {}
    for q in valid_quotes:
        dd = vendor_due_diligence(vendors[q["vendor_id"]], company["as_of"], company["bank_change_cooling_days"])
        diligence[q["vendor_id"]] = dd
        # A dirty vendor blocks the case only if it is the sole option; otherwise it is excluded from sourcing.
        if dd["issues"] and (len(valid_quotes) == 1 or not any(i["severity"] == "BLOCK" for i in dd["issues"])):
            findings += dd["issues"]

    lead_issues = []
    for q in valid_quotes:
        if pr.get("item", {}).get("need_by") and q.get("lead_time_days") is not None:
            slack = days_between(pr["date"], pr["item"]["need_by"]) - PO_PROCESSING_DAYS - q["lead_time_days"]
            if slack < 0:
                lead_issues.append(q["vendor_id"])
    blocked = any(f["severity"] == "BLOCK" for f in findings)
    return {"decision": "BLOCK" if blocked else "PROCEED", "approver": approver, "quote_rule": rule,
            "findings": findings, "budget": budget, "split": split, "vendor_diligence": diligence,
            "excluded_vendors": [v for v, d in diligence.items() if not d["clean"]] if len(valid_quotes) > 1 else [],
            "lead_time_risk_vendors": lead_issues}
