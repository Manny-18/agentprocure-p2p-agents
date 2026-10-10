"""Accounts Payable Specialist: 3-way match, duplicates and bank-fraud controls."""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import inr
from ..rules.matching import bank_change_check, duplicate_check, three_way_match
from .base import StepRecorder
from .personas import PERSONAS


def ap_agent(state: dict) -> dict:
    s, po = state["scenario"], state["po"]
    inv, grn = s["invoice"], s.get("grn")
    co, vendors, rates = config.company(), config.vendors(), config.hsn_rates()
    v = vendors[inv["vendor_id"]]
    rec = StepRecorder("ap")
    findings = []
    if inv["vendor_id"] != po["vendor_id"]:
        findings.append({"code": "INVOICE_VENDOR_NOT_PO_VENDOR", "severity": "BLOCK", "detail": "Invoice is from a different vendor than the PO"})

    rate = rates.get(po["hsn"], {}).get("rate", 18)
    match = three_way_match(po={"unit_price": po["unit_price"], "qty": po["qty"], "freight": po["freight"]},
                            grn=grn, invoice=inv, tolerance=co["match_tolerance"], tax_rate_pct=rate)
    rec.tool("three_way_match", {"po": po["po_no"], "grn": grn and grn["grn_no"], "invoice": inv["invoice_no"]}, match,
             f"{match['status']}: price {match['invoice_price']} vs {match['po_price']} ({match['price_variance_pct']:+}%), "
             f"qty invoiced {match['invoiced_qty']:,} vs accepted {match['accepted_qty']:,}")
    findings += match["exceptions"]
    dup = duplicate_check(inv, s.get("invoice_history", []))
    rec.tool("duplicate_check", {"invoice_no": inv["invoice_no"]}, dup,
             f"Checked against {dup['checked_against']} prior invoice(s): " + ("no duplicate" if not dup["issues"] else dup["issues"][0]["code"]))
    findings += dup["issues"]
    bank = bank_change_check(v, inv, co["as_of"], co["bank_change_cooling_days"])
    rec.tool("bank_change_check", {"vendor": inv["vendor_id"]}, bank,
             "Bank details match master; no recent change" if not bank["issues"] else bank["issues"][0]["code"])
    findings += bank["issues"]

    status = "BLOCKED" if any(f["severity"] == "BLOCK" for f in findings) else ("EXCEPTION" if findings else "MATCHED")
    facts = {"status": status, "match": {k: match[k] for k in ("po_price", "invoice_price", "price_variance_pct", "accepted_qty",
                                                                "invoiced_qty", "approved_total", "billed_total", "disputed_total")},
             "findings": findings}
    if status == "MATCHED":
        fallback = (f"Invoice {inv['invoice_no']} matches PO {po['po_no']} and {grn['grn_no']} within tolerance: "
                    f"{match['invoiced_qty']:,} units at {inr(match['invoice_price'])}. No duplicate, bank details unchanged. "
                    f"Approved for payment: {inr(match['approved_total'])}.")
    else:
        fallback = (f"Invoice {inv['invoice_no']} does not match: " + " ".join(f"{f['detail']}." for f in findings)
                    + f" Payable on the evidence: {inr(match['approved_total'])}; disputed {inr(match['disputed_total'])}.")
    rationale = GATEWAY.narrate(persona=PERSONAS["ap"]["system"], task="Explain the match result and what can be paid.",
                                facts=facts, fallback=fallback)
    report = rec.report(decision={"MATCHED": "Matched - release to tax review", "EXCEPTION": "Exceptions - route to resolver",
                                  "BLOCKED": "Blocked - hold invoice"}[status],
                        findings=findings, rationale=rationale,
                        highlights=[f"Approved {inr(match['approved_total'])}", f"Disputed {inr(match['disputed_total'])}"])
    return {"ap": {"status": status, "match": match, "duplicates": dup, "bank": bank, "findings": findings},
            "trace": [report], "status": f"AP_{status}"}
