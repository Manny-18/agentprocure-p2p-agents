"""Treasury & Working-Capital Analyst: when to pay, and what statutory deadlines are at risk."""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import inr, r2
from ..rules.treasury import plan_invoice_payment, review_open_payables
from .base import StepRecorder
from .personas import PERSONAS


def treasury_agent(state: dict) -> dict:
    s, ap, tax = state["scenario"], state["ap"], state["tax"]
    inv, grn = s["invoice"], s["grn"]
    co, vendors = config.company(), config.vendors()
    v = vendors[inv["vendor_id"]]
    rec = StepRecorder("treasury")
    release = state.get("resolution", {}).get("release_amount", ap["match"]["approved_total"])
    tds_amt = tax["tds"]["tds_amount"]
    net = r2(release - tds_amt)

    plan = plan_invoice_payment(invoice=inv, payable=net, vendor=v, acceptance_date=grn["accepted_date"], company=co)
    rec.tool("payment_timing", {"invoice": inv["invoice_no"], "net_payable": net}, plan,
             f"Due {plan['due_date']}; pay on {plan['pay_on']}" + (" (take discount)" if plan["take_discount"] else ""))
    if plan["discount"]:
        d = plan["discount"]
        rec.tool("discount_apr", {"terms": d["terms"]}, d,
                 f"Discount worth {d['annualised_return_pct']}% annualised vs {d['cost_of_funds_pct']}% cost of funds -> "
                 + ("take" if d["take"] else "skip"))
    alerts = review_open_payables(open_items=s.get("open_payables", []), vendor=v, company=co)
    if s.get("open_payables"):
        rec.tool("msme_open_items_scan", {"vendor": inv["vendor_id"], "open_items": len(s["open_payables"])}, alerts,
                 f"{sum(1 for a in alerts if a['severity'] == 'CRITICAL')} overdue MSME invoice(s); interest accrued "
                 f"{inr(sum(a['interest_accrued'] for a in alerts))}")

    run = [{"invoice_no": inv["invoice_no"], "amount": net, "pay_on": plan["pay_on"], "priority": "MSME-statutory" if plan["msme"]["covered"] else "Contractual"}]
    for a in alerts:
        if a["severity"] == "CRITICAL":
            run.insert(0, {"invoice_no": a["invoice_no"], "amount": r2(a["total"] + a["interest_accrued"]), "pay_on": co["as_of"],
                           "priority": "MSME-OVERDUE (pay now, incl. statutory interest)"})
    findings = [{"code": "MSME_OVERDUE", "severity": "HIGH",
                 "detail": f"{a['invoice_no']} overdue {a['overdue_days']} days since {a['msme_due']}; interest {inr(a['interest_accrued'])} "
                           f"at {a['interest_rate_pct']}% (not tax-deductible); {inr(a['disallowance_if_unpaid_at_year_end'])} disallowed "
                           f"under s.37(2)(g) if still unpaid on {co['tax_year_end']}"} for a in alerts if a["severity"] == "CRITICAL"]
    facts = {"plan": plan, "net_payable": net, "tds": tds_amt, "payment_run": run, "alerts": alerts,
             "cost_of_funds_pct": co["cost_of_funds_pct"], "bank_rate_pct": co["rbi_bank_rate_pct"]}
    fallback = (f"Pay {inr(net)} (after TDS {inr(tds_amt)}) on {plan['pay_on']}. " + ". ".join(plan["reasons"]) + "."
                + (" URGENT: " + " ".join(f["detail"] + "." for f in findings) if findings else ""))
    rationale = GATEWAY.narrate(persona=PERSONAS["treasury"]["system"],
                                task="Recommend the payment timing and any urgent statutory action.", facts=facts, fallback=fallback)
    report = rec.report(decision=f"Schedule {inr(net)} on {plan['pay_on']}" + (f"; pay {len(findings)} overdue MSME invoice(s) today" if findings else ""),
                        findings=findings, rationale=rationale,
                        highlights=[f"Pay on {plan['pay_on']}", f"Net {inr(net)}",
                                    "Discount taken" if plan["take_discount"] else ("Discount skipped" if plan["discount"] else "No discount offered")])
    return {"treasury": {"plan": plan, "net_payable": net, "alerts": alerts, "payment_run": run},
            "trace": [report], "status": "PAYMENT_SCHEDULED"}
