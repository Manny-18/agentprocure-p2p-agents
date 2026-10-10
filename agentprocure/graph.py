"""LangGraph workflow: the end-to-end Procure-to-Pay case as a stateful graph.

    intake -> policy --(BLOCK)--------------------------------------------> controller
                     \--> sourcing crew (CrewAI) -> APPROVAL (human) --(reject)--> controller
                                                          \--> PO -> AP match -> GST/TDS --(exceptions)--> resolver --(hard stop)--> controller
                                                                                      \--> treasury <-----------/ (partial release)
                                                                                               \--> controller -> END
"""
from __future__ import annotations

import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .agents.ap_agent import ap_agent
from .agents.approval import approval_node
from .agents.controller import controller_agent
from .agents.intake import intake_agent
from .agents.po_agent import po_agent
from .agents.policy_agent import policy_agent
from .agents.resolver_agent import resolver_agent
from .agents.sourcing_crew import sourcing_crew_node
from .agents.tax_agent import tax_agent
from .agents.treasury_agent import treasury_agent
from .state import P2PState


def route_after_policy(state: P2PState) -> str:
    return "escalate" if state["policy"]["decision"] == "BLOCK" else "source"


def route_after_approval(state: P2PState) -> str:
    return "approved" if state["approval"]["approved"] else "rejected"


def route_after_po(state: P2PState) -> str:
    return "invoice" if state["scenario"].get("invoice") else "no_invoice"


ACTIONABLE = {"BLOCK", "HOLD"}


def route_after_tax(state: P2PState) -> str:
    issues = state["ap"]["findings"] + state["tax"]["issues"]
    return "exceptions" if any(i["severity"] in ACTIONABLE for i in issues) else "clean"


def route_after_resolver(state: P2PState) -> str:
    return "hold_all" if state["resolution"]["hard_stop"] else "partial"


def build_graph(checkpointer=None):
    g = StateGraph(P2PState)
    g.add_node("intake", intake_agent)
    g.add_node("policy", policy_agent)
    g.add_node("sourcing_crew", sourcing_crew_node)
    g.add_node("approval", approval_node)
    g.add_node("po", po_agent)
    g.add_node("ap", ap_agent)
    g.add_node("tax", tax_agent)
    g.add_node("resolver", resolver_agent)
    g.add_node("treasury", treasury_agent)
    g.add_node("controller", controller_agent)

    g.add_edge(START, "intake")
    g.add_edge("intake", "policy")
    g.add_conditional_edges("policy", route_after_policy, {"escalate": "controller", "source": "sourcing_crew"})
    g.add_edge("sourcing_crew", "approval")
    g.add_conditional_edges("approval", route_after_approval, {"approved": "po", "rejected": "controller"})
    g.add_conditional_edges("po", route_after_po, {"invoice": "ap", "no_invoice": "controller"})
    g.add_edge("ap", "tax")
    g.add_conditional_edges("tax", route_after_tax, {"exceptions": "resolver", "clean": "treasury"})
    g.add_conditional_edges("resolver", route_after_resolver, {"hold_all": "controller", "partial": "treasury"})
    g.add_edge("treasury", "controller")
    g.add_edge("controller", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


GRAPH = None


def get_graph():
    global GRAPH
    if GRAPH is None:
        GRAPH = build_graph()
    return GRAPH


def start_case(scenario: dict, case_id: str | None = None) -> tuple[str, dict]:
    """Run until the human approval interrupt (or the end). Returns (thread_id, state)."""
    case_id = case_id or f"{scenario['id']}-{uuid.uuid4().hex[:6]}"
    if get_graph().get_state({"configurable": {"thread_id": case_id}}).values:   # never reuse a thread
        case_id = f"{case_id}-{uuid.uuid4().hex[:4]}"
    cfg = {"configurable": {"thread_id": case_id}}
    result = get_graph().invoke({"case_id": case_id, "scenario": scenario, "trace": []}, cfg)
    return case_id, result


def pending_approval(result: dict) -> dict | None:
    intr = result.get("__interrupt__")
    if not intr:
        return None
    return intr[0].value


def resume_case(case_id: str, decision: dict) -> dict:
    cfg = {"configurable": {"thread_id": case_id}}
    return get_graph().invoke(Command(resume=decision), cfg)


def run_case(scenario: dict, decision: dict | None = None, case_id: str | None = None) -> dict:
    """Convenience: run a scenario end to end, answering the approval with `decision`."""
    case_id, result = start_case(scenario, case_id)
    if pending_approval(result):
        decision = decision or {"decision": "approve", "comment": "Approved as recommended (auto-approve demo mode)."}
        result = resume_case(case_id, decision)
    return result


def mermaid() -> str:
    return get_graph().get_graph().draw_mermaid()
