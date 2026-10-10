"""FastAPI service so n8n (or any app) can drive the agents.

Run:  uvicorn agentprocure.api:app --reload --port 8000     (Swagger UI at /docs)

  POST /intake/triage            free-text request -> structured PR + missing fields (n8n email intake)
  POST /cases                    start a case (scenario id or full payload); pauses at human approval
  GET  /cases/{case_id}          current state of a case
  POST /cases/{case_id}/decision approver's answer -> resumes the LangGraph run to the end
  GET  /alerts/msme              daily MSME 45-day watch over open payables (n8n schedule)
  POST /policy/ask               Policy Advisor: policy and compliance questions answered with clause citations (RAG)
"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import config
from .agents.advisor import ask_policy
from .agents.intake import ParsedRequest, parse_offline
from .graph import get_graph, pending_approval, resume_case, start_case
from .llm import GATEWAY
from .rules.treasury import review_open_payables

app = FastAPI(title="AgentProcure API", version="1.0.0",
              description="Domain-expert AI agents for Procure-to-Pay (LangGraph + CrewAI). Fictional demo data.")


class StartCase(BaseModel):
    scenario_id: str | None = Field(None, examples=["S1"])
    scenario: dict | None = Field(None, description="Full scenario payload (same shape as data/scenarios/*.json)")
    requested_by: str | None = None


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    approver: str | None = None
    comment: str | None = None


class PolicyQuestion(BaseModel):
    question: str = Field(examples=["Can I split one order into two to avoid getting three quotes?"])


class TriageIn(BaseModel):
    sender: str | None = None
    subject: str | None = None
    body: str


def _summary(case_id: str, result: dict) -> dict:
    pack = pending_approval(result)
    out = {"case_id": case_id, "status": "AWAITING_APPROVAL" if pack else result.get("status"),
           "steps": [{"agent": t["title"], "decision": t["decision"], "findings": [f["code"] for f in t["findings"]]}
                     for t in result.get("trace", [])]}
    if pack:
        out["approval_request"] = pack
    if result.get("memo"):
        out["memo"] = result["memo"]
    return out


@app.get("/health")
def health():
    return {"ok": True, "llm": GATEWAY.label, "crewai": config.USE_CREWAI, "as_of": config.company()["as_of"]}


@app.get("/scenarios")
def scenarios():
    return config.list_scenarios()


@app.post("/intake/triage")
def triage(req: TriageIn):
    text = f"{req.subject}. {req.body}" if req.subject else req.body
    parsed = GATEWAY.extract(persona="You are a Procurement Analyst.", text=text, schema=ParsedRequest) or parse_offline(text)
    missing = [k for k in ("quantity", "need_by", "estimated_value_inr", "category") if getattr(parsed, k) in (None, "")]
    return {"sender": req.sender, "parsed": parsed.model_dump(), "missing_fields": missing,
            "complete": not missing,
            "reply_suggestion": ("Thanks - your request is complete and has been logged for sourcing." if not missing else
                                 "Thanks - to raise the requisition we still need: " + ", ".join(m.replace("_", " ") for m in missing) + ".")}


@app.post("/cases")
def create_case(body: StartCase):
    if body.scenario:
        sc = body.scenario
    elif body.scenario_id:
        try:
            sc = config.load_scenario(body.scenario_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
    else:
        raise HTTPException(422, "Provide scenario_id or scenario")
    case_id, result = start_case(sc)
    return _summary(case_id, result)


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    snap = get_graph().get_state({"configurable": {"thread_id": case_id}})
    if not snap or not snap.values:
        raise HTTPException(404, "Unknown case")
    values = dict(snap.values)
    if snap.interrupts:
        values["__interrupt__"] = snap.interrupts
    return _summary(case_id, values)


@app.post("/cases/{case_id}/decision")
def decide(case_id: str, body: Decision):
    snap = get_graph().get_state({"configurable": {"thread_id": case_id}})
    if not snap or not snap.values:
        raise HTTPException(404, "Unknown case")
    if not snap.interrupts:
        raise HTTPException(409, "Case is not waiting for approval")
    result = resume_case(case_id, body.model_dump())
    return _summary(case_id, result)


@app.get("/alerts/msme")
def msme_alerts(window_days: int = 7):
    co, vendors = config.company(), config.vendors()
    items = config.load_json("payables_register.json")["items"]
    alerts = []
    for vid in sorted({i["vendor_id"] for i in items}):
        v = vendors[vid]
        for a in review_open_payables(open_items=[i for i in items if i["vendor_id"] == vid], vendor=v, company=co):
            if a["overdue_days"] > 0 or a["severity"] in ("CRITICAL", "HIGH"):
                alerts.append({"vendor_id": vid, "vendor": v["name"], "msme_category": v["msme"]["category"], **a})
    alerts.sort(key=lambda a: (a["severity"] != "CRITICAL", a["msme_due"]))
    return {"as_of": co["as_of"], "count": len(alerts), "critical": sum(a["severity"] == "CRITICAL" for a in alerts),
            "alerts": alerts}


@app.post("/policy/ask")
def policy_ask(body: PolicyQuestion):
    return ask_policy(body.question)
