"""Sourcing crew (CrewAI): Category Manager -> Supplier Performance & Risk Analyst -> Negotiation Strategist.

The three CrewAI agents call deterministic tools (Kraljic, scorecard, should-cost) and write the
reasoning. With no API key the crew still runs through CrewAI, driven by an offline "expert" LLM
that follows the same ReAct protocol (Thought -> Action -> Observation -> Final Answer), so the
orchestration you demo offline is the real one.
"""
from __future__ import annotations

import json
import os
import re
import time

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from .. import config  # noqa: E402
from ..llm import GATEWAY, numbers_grounded  # noqa: E402
from ..rules.common import crore, inr, lakh  # noqa: E402
from ..rules.sourcing import kraljic, landed_unit_cost, scorecard, should_cost  # noqa: E402
from .base import StepRecorder  # noqa: E402
from .personas import PERSONAS  # noqa: E402

CASE_CONTEXT: dict[str, dict] = {}


# ------------------------------------------------------------------ deterministic tool logic
def _kraljic_for(ctx: dict) -> dict:
    pr, quotes = ctx["requisition"], ctx["quotes"]
    qty = pr["item"]["qty"]
    avg_landed = sum(landed_unit_cost(q, qty) for q in quotes) / len(quotes)
    return kraljic(annual_spend=round(avg_landed * pr["annual_volume_qty"]), qualified_suppliers=len(quotes),
                   lead_time_days=sum(q["lead_time_days"] for q in quotes) / len(quotes),
                   criticality=pr.get("criticality", "medium"))


def _scorecard_for(ctx: dict) -> dict:
    k = ctx.get("kraljic") or _kraljic_for(ctx)
    return scorecard(quotes=ctx["quotes"], vendors=ctx["vendors"], qty=ctx["requisition"]["item"]["qty"],
                     weights=k["weights"], excluded=ctx["excluded"], infeasible=ctx["infeasible"])


def _negotiation_for(ctx: dict) -> dict:
    k = ctx.get("kraljic") or _kraljic_for(ctx)
    sc = ctx.get("scorecard") or _scorecard_for(ctx)
    win, runner = sc["recommended"], sc["runner_up"]
    pr = ctx["requisition"]
    sh = should_cost(ctx.get("should_cost"), win["unit_price"], pr["item"]["qty"], pr["annual_volume_qty"])
    plan = {"vendor_id": win["vendor_id"], "quoted_unit_price": win["unit_price"], "should_cost": sh,
            "batna": ({"vendor_id": runner["vendor_id"], "vendor": runner["vendor"], "landed_unit_cost": runner["landed_unit_cost"],
                       "weighted_total": runner["weighted_total"]} if runner else None),
            "levers": k["levers"]}
    if sh:
        plan["target_unit_price"] = sh["should_cost"] if sh["gap_pct"] > 1.0 else win["unit_price"]
        plan["opening_ask"] = round(min(sh["should_cost"], win["unit_price"]) * 0.99, 2) if sh["gap_pct"] > 1.0 else None
    return plan


# ------------------------------------------------------------------ offline expert writers
def _write_category(obs: dict) -> str:
    w = ", ".join(f"{k} {int(v * 100)}%" for k, v in obs["weights"].items())
    spend = crore(obs["annual_spend"]) if obs["annual_spend"] >= 1e7 else lakh(obs["annual_spend"])
    return (f"Kraljic position: {obs['quadrant']}. Annual spend {spend} gives {obs['profit_impact']} profit impact; "
            f"supply-risk score {obs['supply_risk_score']} gives {obs['supply_risk']} supply risk. "
            f"Evaluate suppliers with weights: {w}. Strategy levers: " + "; ".join(obs["levers"]) + ".")


def _write_scorecard(obs: dict) -> str:
    lines = []
    for r in obs["ranking"]:
        tag = f" [{r['note']}]" if r["note"] else ""
        lines.append(f"{r['vendor_id']} {r['vendor']}: {r['weighted_total']} pts, landed {inr(r['landed_unit_cost'])}/unit, "
                     f"lead {r['lead_time_days']} days{tag}")
    win, cheap = obs["recommended"], obs["cheapest"]
    note = ""
    if cheap["vendor_id"] != win["vendor_id"]:
        note = (f" The cheapest quote ({cheap['vendor_id']}, {inr(cheap['landed_unit_cost'])}/unit) loses on quality, delivery "
                f"or eligibility, so lowest price is not best value here.")
    margin = f" Margin over runner-up: {obs['margin_vs_runner_up']} pts." if obs["margin_vs_runner_up"] is not None else ""
    return ("Ranking: " + " | ".join(lines) + "." + note + margin +
            f"\nRECOMMENDED_VENDOR: {win['vendor_id']}")


def _write_negotiation(obs: dict) -> str:
    sh = obs.get("should_cost")
    parts = []
    if sh:
        parts.append(f"Should-cost {inr(sh['should_cost'])}/unit (material {inr(sh['material_cost'])} + conversion "
                     f"{inr(sh['conversion'])} + secondary ops {inr(sh['secondary_ops'])} + {sh['overhead_margin_pct']}% overhead and margin) "
                     f"vs quote {inr(sh['quoted'])}: gap {sh['gap_pct']}%. Verdict: {sh['verdict']}.")
        if sh["gap_pct"] > 1.0:
            parts.append(f"Target {inr(obs['target_unit_price'])}/unit, open at {inr(obs['opening_ask'])}. "
                         f"Value at stake {inr(sh['saving_this_order'])} on this order, {inr(sh['saving_annualised'])} a year.")
    if obs.get("batna"):
        b = obs["batna"]
        parts.append(f"BATNA: {b['vendor_id']} {b['vendor']} at {inr(b['landed_unit_cost'])}/unit landed ({b['weighted_total']} pts).")
    parts.append("Levers: " + "; ".join(obs["levers"]) + ".")
    return " ".join(parts)


ROLE_PLAYBOOK = {  # role -> (tool name, writer)
    PERSONAS["category_manager"]["title"]: ("kraljic_analysis", _write_category),
    PERSONAS["supplier_analyst"]["title"]: ("supplier_scorecard", _write_scorecard),
    PERSONAS["negotiator"]["title"]: ("should_cost_model", _write_negotiation),
}


def _build_offline_llm():
    from crewai.llms.base_llm import BaseLLM

    class OfflineExpertLLM(BaseLLM):
        """Deterministic stand-in for an LLM that speaks CrewAI's ReAct protocol."""

        def call(self, messages, tools=None, callbacks=None, available_functions=None,
                 from_task=None, from_agent=None, response_model=None):
            msgs = messages if isinstance(messages, list) else [{"role": "user", "content": messages}]
            text = "\n".join(str(m.get("content", "")) for m in msgs)
            case = re.search(r"Case ID: ([A-Za-z0-9_\-]+)", text)
            case_id = case.group(1) if case else "unknown"
            role = from_agent.role if from_agent else ""
            tool_name, writer = ROLE_PLAYBOOK[role]
            observed = [m for m in msgs if m.get("role") == "assistant" and "Observation:" in str(m.get("content", ""))]
            if not observed:
                return (f"Thought: I need the {tool_name.replace('_', ' ')} before I can advise.\n"
                        f"Action: {tool_name}\nAction Input: {json.dumps({'case_id': case_id})}")
            obs_text = str(observed[-1]["content"]).split("Observation:", 1)[1].strip()
            try:
                obs = json.loads(obs_text)
            except json.JSONDecodeError:
                obs = json.loads(obs_text[: obs_text.rfind("}") + 1])
            return f"Thought: I now know the final answer\nFinal Answer: {writer(obs)}"

        def supports_function_calling(self) -> bool:
            return False

        def get_context_window_size(self) -> int:
            return 32000

    return OfflineExpertLLM(model="offline-expert")


def _build_real_llm():
    from crewai import LLM
    prefix = {"gemini": "gemini", "openai": "openai", "anthropic": "anthropic", "ollama": "ollama"}[GATEWAY.provider]
    kwargs = {"temperature": config.LLM_TEMPERATURE}
    if GATEWAY.provider in ("openai", "anthropic"):
        return LLM(model=GATEWAY.model, provider=prefix, **kwargs)
    return LLM(model=f"{prefix}/{GATEWAY.model}", **kwargs)


def build_crew(llm):
    from crewai import Agent, Crew, Process, Task
    from crewai.tools import tool

    @tool("kraljic_analysis")
    def kraljic_tool(case_id: str) -> str:
        """Classify the purchase in the Kraljic matrix and return evaluation weights and levers for the case."""
        ctx = CASE_CONTEXT[case_id]
        ctx["kraljic"] = _kraljic_for(ctx)
        ctx.setdefault("tool_log", []).append("kraljic_analysis")
        return json.dumps(ctx["kraljic"])

    @tool("supplier_scorecard")
    def scorecard_tool(case_id: str) -> str:
        """Score every quote on price (landed), quality (PPM), delivery (OTIF), financial risk and compliance."""
        ctx = CASE_CONTEXT[case_id]
        ctx["scorecard"] = _scorecard_for(ctx)
        ctx.setdefault("tool_log", []).append("supplier_scorecard")
        return json.dumps(ctx["scorecard"])

    @tool("should_cost_model")
    def should_cost_tool(case_id: str) -> str:
        """Build the should-cost target, BATNA and negotiation levers for the recommended supplier."""
        ctx = CASE_CONTEXT[case_id]
        ctx["negotiation"] = _negotiation_for(ctx)
        ctx.setdefault("tool_log", []).append("should_cost_model")
        return json.dumps(ctx["negotiation"])

    def agent(key, tools):
        p = PERSONAS[key]
        return Agent(role=p["title"], goal=p["mandate"], backstory=p["system"] + " Use only numbers returned by your tool.",
                     tools=tools, llm=llm, allow_delegation=False, verbose=False, max_iter=4)

    cm, sa, ns = agent("category_manager", [kraljic_tool]), agent("supplier_analyst", [scorecard_tool]), agent("negotiator", [should_cost_tool])
    t1 = Task(description="Case ID: {case_id}. Position this purchase ({item}) in the Kraljic matrix using the kraljic_analysis tool "
                          "and state the sourcing strategy and evaluation weights.",
              expected_output="Quadrant, why, weights and strategy levers in under 120 words.", agent=cm)
    t2 = Task(description="Case ID: {case_id}. Rank the quotes with the supplier_scorecard tool. Explain the trade-offs. "
                          "Only eligible suppliers can be recommended. End with a line 'RECOMMENDED_VENDOR: <vendor_id>'.",
              expected_output="Ranking with points, the trade-off, and the RECOMMENDED_VENDOR line.", agent=sa, context=[t1])
    t3 = Task(description="Case ID: {case_id}. Use the should_cost_model tool to prepare the negotiation: target price, "
                          "opening ask, BATNA and three levers.",
              expected_output="Negotiation brief in under 140 words.", agent=ns, context=[t1, t2])
    _silence_first_run_tracing_prompt()
    online = not getattr(llm, "model", "").startswith("offline")
    return Crew(agents=[cm, sa, ns], tasks=[t1, t2, t3], process=Process.sequential, verbose=False, tracing=False,
                max_rpm=config.CREW_MAX_RPM if online else None)  # CrewAI's own rate limiter, for free tiers


def _silence_first_run_tracing_prompt():
    """CrewAI asks an interactive y/N question about cloud traces on its first run, which would
    hang an API server or a demo. Record the same answer as pressing 'N' (no traces are sent)."""
    try:
        from crewai.events.listeners.tracing.utils import is_first_execution, mark_first_execution_done
        if is_first_execution():
            mark_first_execution_done(user_consented=False)
    except Exception:
        pass


def sourcing_crew_node(state: dict) -> dict:
    s, pr, pol = state["scenario"], state["requisition"], state["policy"]
    case_id = state["case_id"]
    rec = StepRecorder("supplier_analyst")
    ctx = {"requisition": pr, "quotes": s["quotes"], "vendors": config.vendors(), "should_cost": s.get("should_cost"),
           "excluded": pol.get("excluded_vendors", []), "infeasible": pol.get("lead_time_risk_vendors", [])}
    CASE_CONTEXT[case_id] = ctx

    engine, outputs, crew_error = "deterministic", None, None
    t0 = time.perf_counter()
    if config.USE_CREWAI:
        try:
            llm = _build_real_llm() if GATEWAY.online else _build_offline_llm()
            crew = build_crew(llm)
            result = crew.kickoff(inputs={"case_id": case_id, "item": pr["item"]["description"]})
            outputs = [t.raw for t in result.tasks_output]
            engine = f"CrewAI ({'LLM: ' + GATEWAY.label if GATEWAY.online else 'offline expert LLM'})"
        except Exception as exc:  # fall back to the same tools without the crew
            crew_error = f"{type(exc).__name__}: {exc}"[:300]
    # Deterministic results are the source of truth for decisions
    k = ctx.get("kraljic") or _kraljic_for(ctx)
    ctx["kraljic"] = k
    sc = ctx.get("scorecard") or _scorecard_for(ctx)
    ctx["scorecard"] = sc
    neg = ctx.get("negotiation") or _negotiation_for(ctx)
    offline_texts = [_write_category(k), _write_scorecard(sc), _write_negotiation(neg)]

    guard_notes, texts = [], []
    if outputs:
        facts = [k, sc, neg]
        for i, txt in enumerate(outputs):
            ok, bad = numbers_grounded(txt, facts[i])
            if ok:
                texts.append(txt)
            else:
                texts.append(offline_texts[i])
                guard_notes.append(f"task {i + 1}: ungrounded figures {bad[:3]} -> replaced with tool-based text")
    else:
        texts = offline_texts

    winner = sc["recommended"]
    m = re.search(r"RECOMMENDED_VENDOR:\s*(V-\d+)", texts[1])
    if m and winner and m.group(1) != winner["vendor_id"]:
        guard_notes.append(f"LLM recommended {m.group(1)}; overruled by scorecard winner {winner['vendor_id']}")

    crew_members = []
    for key, txt in zip(("category_manager", "supplier_analyst", "negotiator"), texts):
        crew_members.append({"agent": key, "title": PERSONAS[key]["title"], "output": txt.replace("RECOMMENDED_VENDOR:", "Recommended vendor:")})

    rec.tool("kraljic_analysis", {"case_id": case_id}, k, f"{k['quadrant']} (spend {inr(k['annual_spend'])}, risk score {k['supply_risk_score']})")
    rec.tool("supplier_scorecard", {"case_id": case_id}, sc,
             f"Winner {winner['vendor_id']} {winner['weighted_total']} pts" + (f"; runner-up {sc['runner_up']['vendor_id']}" if sc["runner_up"] else ""))
    sh = neg.get("should_cost")
    rec.tool("should_cost_model", {"case_id": case_id}, neg,
             (f"Should-cost {inr(sh['should_cost'])} vs quote {inr(sh['quoted'])} ({sh['gap_pct']}% gap)" if sh else "No should-cost model supplied"))
    report = rec.report(decision=f"Recommend {winner['vendor_id']} {winner['vendor']} at {inr(winner['unit_price'])}/unit",
                        rationale={"text": texts[1].split("\nRECOMMENDED_VENDOR")[0], "source": engine,
                                   "guardrail": "; ".join(guard_notes) or "passed"},
                        highlights=[f"Kraljic: {k['quadrant']}", f"Winner {winner['weighted_total']} pts",
                                    f"Target {inr(neg.get('target_unit_price'))}" if neg.get("target_unit_price") else "No target"],
                        extra={"title": "Sourcing Crew (3 CrewAI agents)", "framework": "CrewAI crew inside a LangGraph node",
                               "crew": crew_members, "engine": engine, "crew_error": crew_error,
                               "crew_tool_calls": ctx.get("tool_log", []),
                               "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)})
    CASE_CONTEXT.pop(case_id, None)
    sourcing = {"kraljic": k, "scorecard": sc, "negotiation": neg, "recommended_vendor": winner["vendor_id"],
                "recommended_quote": next(q for q in s["quotes"] if q["vendor_id"] == winner["vendor_id"]),
                "engine": engine, "crew": crew_members}
    return {"sourcing": sourcing, "trace": [report], "status": "SOURCING_RECOMMENDED"}
