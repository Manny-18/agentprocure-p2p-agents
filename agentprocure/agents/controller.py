"""Finance Controller: closes the case with a CFO memo, KPIs and the audit trail."""
from __future__ import annotations

from ..llm import GATEWAY
from ..rules.common import inr
from .base import StepRecorder
from .personas import PERSONAS


def _final_status(state: dict) -> str:
    if state.get("status") == "POLICY_BLOCKED":
        return "ESCALATED"
    if state.get("status") == "REJECTED":
        return "REJECTED"
    res = state.get("resolution")
    if res:
        return "ON_HOLD" if res["hard_stop"] else "COMPLETED_WITH_HOLD"
    if state.get("treasury"):
        return "COMPLETED"
    return "PO_ISSUED_AWAITING_INVOICE" if state.get("po") else "OPEN"


def kpis(state: dict) -> dict:
    trace = state.get("trace", [])
    findings = [f for t in trace for f in t.get("findings", [])]
    ap, tax, tr, src = state.get("ap"), state.get("tax"), state.get("treasury"), state.get("sourcing")
    neg = (src or {}).get("negotiation", {})
    sh = neg.get("should_cost") or {}
    alerts = (tr or {}).get("alerts", [])
    return {
        "agents_involved": len({t["agent"] for t in trace}) + (2 if src else 0),   # crew adds 2 more agents
        "tool_calls": sum(len(t.get("tools", [])) for t in trace),
        "controls_flagged": len(findings),
        "blocking_controls": sum(1 for f in findings if f["severity"] == "BLOCK"),
        "human_touchpoints": (1 if state.get("approval") else 0) + (1 if state.get("resolution") else 0) + (1 if state.get("status") == "POLICY_BLOCKED" else 0),
        "touchless_invoice": bool(ap and ap["status"] == "MATCHED" and tax
                                  and not any(i["severity"] in ("BLOCK", "HOLD") for i in tax["issues"])),
        "agent_processing_ms": round(sum(t.get("elapsed_ms", 0) for t in trace), 1),
        "po_value_incl_gst": state.get("po", {}).get("tax", {}).get("invoice_total"),
        "approved_payable": ap["match"]["approved_total"] if ap else None,
        "disputed_amount_protected": ap["match"]["disputed_total"] if ap else None,
        "tds_withheld": tax["tds"]["tds_amount"] if tax else None,
        "itc_claimable": tax["itc_amount"] if tax else None,
        "negotiation_value_this_order": sh.get("saving_this_order"),
        "negotiation_value_annual": sh.get("saving_annualised"),
        "msme_interest_accrued": round(sum(a["interest_accrued"] for a in alerts), 2) if alerts else 0.0,
        "discount_decision": (tr["plan"]["discount"]["take"] if tr and tr["plan"].get("discount") else None),
    }


def controller_agent(state: dict) -> dict:
    rec = StepRecorder("controller")
    status = _final_status(state)
    k = kpis(state)
    pr = state["requisition"]
    bullets = [f"Case {state['case_id']} - {pr['pr_no']}: {pr['item']['description']} ({pr['item']['qty']:,} {pr['item']['uom']})."]
    if status == "ESCALATED":
        blocks = [f for f in state["policy"]["findings"] if f["severity"] == "BLOCK"]
        bullets += ["Outcome: ESCALATED. No PO, no payment. Hard stops: " + "; ".join(f["code"] for f in blocks) + ".",
                    "Required before re-submission: call-back verification of the vendor's bank change using master-data contacts; "
                    "correct GSTIN/PAN on the vendor master after GST portal verification; consolidate the related requisitions "
                    "and run a competitive RFQ; budget re-validation for the cost center.",
                    "Internal Audit notified: pattern matches threshold-splitting plus a bank-change request (business email compromise risk)."]
    elif status == "REJECTED":
        bullets.append(f"Outcome: REJECTED by {state['approval']['approved_by']}. {state['approval'].get('comment', '')}")
    else:
        src, po, tr = state["sourcing"], state["po"], state.get("treasury")
        win = src["scorecard"]["recommended"]
        bullets.append(f"Sourcing: {win['vendor']} selected ({win['weighted_total']} pts, Kraljic {src['kraljic']['quadrant']}); "
                       f"approved by {state['approval']['approved_by']}; {po['po_no']} for {inr(po['tax']['invoice_total'])} incl. GST.")
        if state.get("ap"):
            m = state["ap"]["match"]
            bullets.append(f"Invoice: {state['ap']['status'].lower()}; approved {inr(m['approved_total'])}"
                           + (f", {inr(m['disputed_total'])} held for credit note" if m["disputed_total"] > 0.5 else "") + ".")
        if state.get("tax"):
            t = state["tax"]
            bullets.append(f"Tax: ITC {inr(t['itc_amount'])} claimable; TDS {inr(t['tds']['tds_amount'])} ({t['tds']['reason'][0].lower() + t['tds']['reason'][1:]}).")
        if tr:
            bullets.append(f"Cash: pay {inr(tr['net_payable'])} on {tr['plan']['pay_on']}." +
                           (" " + " ".join(f"Overdue MSME invoice {a['invoice_no']} ({a['overdue_days']} days late, "
                                          f"interest {inr(a['interest_accrued'])}) must be paid today." for a in tr["alerts"] if a["severity"] == "CRITICAL")))
        if k["negotiation_value_annual"]:
            bullets.append(f"Upside: should-cost gap worth {inr(k['negotiation_value_annual'])} a year on this part if negotiated to target.")
    fallback = "\n".join("- " + b for b in bullets)
    facts = {"status": status, "kpis": k, "bullets": bullets}
    rationale = GATEWAY.narrate(persona=PERSONAS["controller"]["system"],
                                task="Write a CFO case memo of 4-6 bullet points: outcome, money impact, risks, next actions.",
                                facts=facts, fallback=fallback, max_words=180)
    report = rec.report(decision=f"Case closed: {status}", rationale=rationale,
                        highlights=[f"Status {status}", f"{k['tool_calls']} tool calls", f"{k['human_touchpoints']} human touchpoint(s)"])
    return {"memo": {"status": status, "bullets": bullets, "text": rationale["text"], "kpis": k},
            "trace": [report], "status": status}
