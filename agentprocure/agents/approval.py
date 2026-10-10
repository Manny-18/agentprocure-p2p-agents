"""Human-in-the-loop approval gate (LangGraph interrupt).

The graph pauses here and hands the approver a decision pack. It resumes with
{"decision": "approve" | "reject", "approver": "...", "comment": "..."}.
"""
from __future__ import annotations

from langgraph.types import interrupt

from ..rules.common import inr
from .base import StepRecorder


def approval_pack(state: dict) -> dict:
    pr, pol, src = state["requisition"], state["policy"], state["sourcing"]
    win = src["scorecard"]["recommended"]
    q = src["recommended_quote"]
    value = round(q["unit_price"] * pr["item"]["qty"] + (q.get("freight") or 0), 2)
    neg = src["negotiation"]
    return {
        "case_id": state["case_id"],
        "approver_role": pol["approver"],
        "pr_no": pr["pr_no"],
        "item": pr["item"]["description"],
        "qty": pr["item"]["qty"],
        "vendor_id": win["vendor_id"],
        "vendor": win["vendor"],
        "po_value_excl_gst": value,
        "score": win["weighted_total"],
        "runner_up": src["scorecard"]["runner_up"]["vendor_id"] if src["scorecard"]["runner_up"] else None,
        "kraljic": src["kraljic"]["quadrant"],
        "warnings": [f["detail"] for f in pol["findings"] if f["severity"] == "WARN"],
        "negotiation_target": neg.get("target_unit_price"),
        "question": f"Approve PO to {win['vendor']} for {inr(value)} (excl. GST)?",
    }


def approval_node(state: dict) -> dict:
    pack = approval_pack(state)
    answer = interrupt(pack)                      # graph pauses here until a human answers
    if isinstance(answer, str):
        answer = {"decision": answer}
    decision = str(answer.get("decision", "reject")).lower()
    approved = decision in ("approve", "approved", "yes", "y")
    who = answer.get("approver") or pack["approver_role"]
    rec = StepRecorder("approver")
    rec.tool("approval_pack", {"case_id": state["case_id"]}, pack, pack["question"])
    report = rec.report(decision=("APPROVED" if approved else "REJECTED") + f" by {who}",
                        rationale={"text": answer.get("comment") or ("Approved as recommended." if approved else "Rejected."),
                                   "source": "human", "guardrail": "n/a"},
                        highlights=[f"Role required: {pack['approver_role']}", f"Value {inr(pack['po_value_excl_gst'])}"])
    return {"approval": {**pack, "approved": approved, "approved_by": who, "comment": answer.get("comment", "")},
            "trace": [report], "status": "APPROVED" if approved else "REJECTED"}
