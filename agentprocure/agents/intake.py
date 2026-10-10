"""Procurement Analyst: free-text request -> structured, policy-ready requisition."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from .. import config
from ..knowledge import excerpt, kb
from ..llm import GATEWAY
from ..rules.common import days_between, inr
from ..rules.policy import budget_check
from .base import StepRecorder
from .personas import PERSONAS

CATEGORY_KEYWORDS = {
    "aluminium castings": ["die-cast", "die cast", "casting", "adc12", "housing"],
    "machined components": ["shaft", "machined", "cnc", "turned", "en8"],
    "electrical panels": ["panel", "plc", "vfd", "switchgear"],
    "packaging": ["bag", "film", "packaging", "carton", "vci"],
    "MRO": ["bolt", "fastener", "glove", "spare", "bearing", "tool", "lubricant"],
}
CATEGORY_HSN = {"aluminium castings": "7616", "machined components": "8483", "electrical panels": "8537", "packaging": "3923"}
SPEND_CLASS = {"aluminium castings": "Direct material", "machined components": "Direct material",
               "electrical panels": "Capex / maintenance", "packaging": "Indirect - consumables", "MRO": "Indirect - MRO"}


class ParsedRequest(BaseModel):
    """Fields an analyst needs from a purchase request."""
    item_description: str = Field(description="What is being bought")
    quantity: float | None = Field(None, description="Quantity requested")
    uom: str | None = Field(None, description="Unit of measure, e.g. nos, lot")
    need_by: str | None = Field(None, description="Required date as YYYY-MM-DD")
    estimated_value_inr: float | None = Field(None, description="Estimated value in rupees (convert lakh/crore)")
    category: str | None = Field(None, description=f"One of {list(CATEGORY_KEYWORDS)}")
    urgent: bool = Field(False, description="Request uses urgency language")
    sole_source_claimed: bool = Field(False, description="Requester asks for a specific single supplier")


def parse_offline(text: str) -> ParsedRequest:
    t = text.lower()
    qty = uom = None
    m = re.search(r"(\d[\d,]*)\s*(nos|pcs|units|rolls|kits|lot)\b", t)
    if m:
        qty, uom = float(m.group(1).replace(",", "")), m.group(2)
    elif re.search(r"\b1 lot\b|\(.*1 lot\)", t):
        qty, uom = 1.0, "lot"
    else:
        m = re.search(r"\b(\d{3,6})\b", t)
        if m:
            qty, uom = float(m.group(1)), "nos"
    if qty is None and "1 lot" in t:
        qty, uom = 1.0, "lot"
    value = None
    m = re.search(r"rs\.?\s*([\d.]+)\s*(lakh|crore)", t)
    if m:
        value = float(m.group(1)) * (1e5 if m.group(2) == "lakh" else 1e7)
    need_by = None
    m = re.search(r"by (\d{1,2} [a-z]{3,9} \d{4})", t)
    if m:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                need_by = datetime.strptime(m.group(1).title(), fmt).date().isoformat()
                break
            except ValueError:
                pass
    category = next((c for c, kws in CATEGORY_KEYWORDS.items() if any(k in t for k in kws)), None)
    return ParsedRequest(item_description=text[:120], quantity=qty, uom=uom, need_by=need_by,
                         estimated_value_inr=value, category=category,
                         urgent=any(w in t for w in ("urgent", "asap", "approve fast", "immediately")),
                         sole_source_claimed=any(w in t for w in ("sole source", "single source", "only vendor")))


def intake_agent(state: dict) -> dict:
    s = state["scenario"]
    pr = s["requisition"]
    co = config.company()
    rec = StepRecorder("intake")

    parsed = GATEWAY.extract(persona=PERSONAS["intake"]["system"], text=pr["request_text"], schema=ParsedRequest)
    method = GATEWAY.label if parsed else "offline rule-based parser"
    if parsed is None:
        parsed = parse_offline(pr["request_text"])
    rec.tool("parse_request", {"text": pr["request_text"]}, parsed,
             f"Extracted qty={parsed.quantity} {parsed.uom or ''}, need-by={parsed.need_by}, "
             f"value={inr(parsed.estimated_value_inr) if parsed.estimated_value_inr else 'n/a'}, category={parsed.category} ({method})")

    findings = []
    if parsed.quantity and abs(parsed.quantity - pr["item"]["qty"]) > 0.5:
        findings.append({"code": "QTY_MISMATCH", "severity": "WARN",
                         "detail": f"Text says {parsed.quantity}, form says {pr['item']['qty']}"})
    if parsed.category and parsed.category != pr["category"]:
        findings.append({"code": "CATEGORY_MISMATCH", "severity": "WARN",
                         "detail": f"Text suggests '{parsed.category}', form says '{pr['category']}'"})
    hsn = pr["item"].get("hsn") or CATEGORY_HSN.get(pr["category"])
    if parsed.urgent:
        findings.append({"code": "URGENCY_LANGUAGE", "severity": "INFO",
                         "detail": "Request pressures for speed; urgency is a common lever in policy bypass"})
    if parsed.sole_source_claimed:
        findings.append({"code": "SOLE_SOURCE_CLAIMED", "severity": "INFO", "detail": "Requester names a single supplier"})

    reminders = []
    queries = []
    if parsed.urgent:
        queries.append("urgent request pressure to approve fast emergency purchase")
    if parsed.sole_source_claimed or pr.get("single_source"):
        queries.append("buy from one supplier only sole source justification")
    for q in queries:
        hit = kb().retrieve(q, k=1)
        if hit and hit[0]["clause"] not in {r["clause"] for r in reminders}:
            reminders.append({"clause": hit[0]["clause"], "title": hit[0]["title"], "excerpt": excerpt(hit[0]["text"])})
    if queries:
        rec.tool("policy_knowledge_base", {"queries": queries, "retrieval": kb().mode}, reminders,
                 "Retrieved " + ", ".join(f"{r['clause']} {r['title']}" for r in reminders))

    lead_days = days_between(pr["date"], pr["item"]["need_by"])
    budget = rec.tool("budget_check", {"cost_center": pr["cost_center"], "amount": pr["estimated_value"]},
                      budget_check(pr["cost_center"], pr["estimated_value"], co["budgets"]),
                      "")
    rec.tools[-1]["summary"] = (f"{budget['name']}: remaining {inr(budget['remaining'])} vs request {inr(pr['estimated_value'])}"
                                if budget.get("name") else "cost center not found")
    requisition = {**pr, "policy_reminders": reminders, "hsn": hsn, "spend_class": SPEND_CLASS.get(pr["category"], "Unclassified"),
                   "days_to_need_by": lead_days, "parsed": parsed.model_dump(), "parse_method": method,
                   "budget": {"remaining": budget["remaining"], "ok": budget["ok"]}}
    facts = {"pr_no": pr["pr_no"], "item": pr["item"]["description"], "qty": pr["item"]["qty"],
             "estimated_value": pr["estimated_value"], "need_by": pr["item"]["need_by"],
             "days_to_need_by": lead_days, "spend_class": requisition["spend_class"], "hsn": hsn,
             "budget_remaining": budget["remaining"], "flags": [f["code"] for f in findings],
             "policy_reminders": reminders}
    fallback = (f"{pr['pr_no']} is a {requisition['spend_class'].lower()} request for {pr['item']['qty']:,} {pr['item']['uom']} of "
                f"{pr['item']['description']} (HSN {hsn}), estimated at {inr(pr['estimated_value'])} and needed in {lead_days} days. "
                f"Budget on {pr['cost_center']} has {inr(budget['remaining'])} available. "
                + ("Flags for the policy officer: " + ", ".join(f["code"] for f in findings) + "." if findings else
                   "The request is complete and consistent with the form.")
                + ("".join(f" Reminder to the requester ({r['clause']}, {r['title']}): {r['excerpt']}" for r in reminders)))
    rationale = GATEWAY.narrate(persona=PERSONAS["intake"]["system"],
                                task="Summarise this requisition for the policy officer in 2-3 sentences and list any flags.",
                                facts=facts, fallback=fallback)
    report = rec.report(decision="Requisition structured and forwarded to Policy & Compliance",
                        findings=findings, rationale=rationale,
                        highlights=[f"{pr['item']['qty']:,} {pr['item']['uom']} | {inr(pr['estimated_value'])}",
                                    f"{requisition['spend_class']} | HSN {hsn}", f"Need-by in {lead_days} days"])
    return {"requisition": requisition, "trace": [report], "status": "REQUISITION_READY"}
