"""Policy & Compliance Officer: DoA, competitive quotes, split purchases, budget, vendor KYC."""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import inr
from ..rules.policy import check_requisition
from .base import StepRecorder, severity_counts
from .personas import PERSONAS


def policy_agent(state: dict) -> dict:
    s = state["scenario"]
    pr = state["requisition"]
    co, vendors = config.company(), config.vendors()
    rec = StepRecorder("policy")

    result = check_requisition(pr, s["quotes"], vendors, co, s.get("pr_history", []))
    rec.tool("delegation_of_authority", {"value": pr["estimated_value"]}, None,
             f"Approver for {inr(pr['estimated_value'])}: {result['approver']}")
    rec.tool("competitive_quote_rule", {"value": pr["estimated_value"], "quotes": len(s["quotes"])}, None,
             f"Needs {result['quote_rule']['min_quotes']} quote(s); received {len(s['quotes'])}")
    rec.tool("split_purchase_scan", {"window_days": co["split_window_days"], "history": len(s.get("pr_history", []))}, None,
             f"{len(result['split']['related'])} related PR(s); combined {inr(result['split']['combined_value'])}")
    rec.tool("budget_check", {"cost_center": pr["cost_center"]}, None,
             f"Remaining {inr(result['budget']['remaining'])}; " + ("OK" if result["budget"]["ok"] else "issue raised"))
    for vid, dd in result["vendor_diligence"].items():
        rec.tool("vendor_due_diligence", {"vendor_id": vid}, None,
                 f"{dd['vendor']}: " + ("clean" if not dd["issues"] else ", ".join(i["code"] for i in dd["issues"])))

    findings = result["findings"]
    blocked = result["decision"] == "BLOCK"
    counts = severity_counts(findings)
    facts = {"decision": result["decision"], "approver": result["approver"], "findings": findings,
             "excluded_vendors": result["excluded_vendors"], "lead_time_risk_vendors": result["lead_time_risk_vendors"]}
    if blocked:
        fallback = ("STOP. This requisition cannot proceed. " + " ".join(f"{f['detail']}." for f in findings if f["severity"] == "BLOCK")
                    + " Route to the Procurement Head and Internal Audit; the bank change must be verified by call-back on a "
                      "number from the vendor master before any payment, and the related requisitions must be consolidated and re-sourced competitively.")
    else:
        fallback = (f"Policy checks passed. Approval authority: {result['approver']}. "
                    + (" Notes for the approver: " + " ".join(f"{f['detail']}." for f in findings) if findings else "No warnings.")
                    + (f" Excluded from sourcing on lead time: {', '.join(result['lead_time_risk_vendors'])}." if result["lead_time_risk_vendors"] else ""))
    rationale = GATEWAY.narrate(persona=PERSONAS["policy"]["system"],
                                task="State the policy verdict, the approver, and each finding with the rule behind it.",
                                facts=facts, fallback=fallback)
    report = rec.report(decision=("BLOCKED - escalate, do not source" if blocked else f"Cleared for sourcing; approver = {result['approver']}"),
                        findings=findings, rationale=rationale,
                        highlights=[f"Approver: {result['approver']}",
                                    f"Findings: {counts.get('BLOCK', 0)} block / {counts.get('WARN', 0)} warn"])
    return {"policy": result, "trace": [report], "status": "POLICY_BLOCKED" if blocked else "POLICY_CLEARED"}
