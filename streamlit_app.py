"""AgentProcure on Streamlit: the real agents, run live on every click.

    streamlit run streamlit_app.py

Unlike the static demo page, nothing here is replayed: each button runs the LangGraph case graph, the CrewAI
sourcing crew, the rules and the RAG knowledge base in this Python process. Offline by default; set
LLM_PROVIDER and GOOGLE_API_KEY (in .env locally, or in the app's Secrets on Streamlit Cloud) to use Gemini.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid

import streamlit as st

st.set_page_config(page_title="AgentProcure: P2P agents", page_icon="📦", layout="wide")

# Streamlit Cloud keeps keys in st.secrets; the agents read environment variables, so copy them across first.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)):
            os.environ.setdefault(_k, str(_v))
except Exception:  # no secrets file: run offline
    pass

from agentprocure import config  # noqa: E402
from agentprocure.agents.advisor import ask_policy  # noqa: E402
from agentprocure.graph import get_graph, pending_approval, resume_case, run_case, start_case  # noqa: E402
from agentprocure.knowledge import kb  # noqa: E402
from agentprocure.llm import GATEWAY  # noqa: E402
from agentprocure.rules.common import inr  # noqa: E402
from evals.run_evals import CASES, all_codes, patched  # noqa: E402

REPO = "https://github.com/Manny-18/agentprocure-p2p-agents"
MONEY = {"po_value_incl_gst", "approved_payable", "disputed_amount_protected", "tds_withheld", "itc_claimable",
         "negotiation_value_this_order", "negotiation_value_annual", "msme_interest_accrued"}
SEVERITY_COLOR = {"BLOCK": "red", "HOLD": "orange", "HIGH": "red", "WARN": "orange", "INFO": "blue"}
STATUS_STYLE = {"COMPLETED": "success", "COMPLETED_WITH_HOLD": "warning", "ON_HOLD": "warning",
                "ESCALATED": "error", "REJECTED": "error"}
NODE_LABEL = {"intake": "Procurement Analyst", "policy": "Policy & Compliance", "sourcing_crew": "Sourcing crew\n(CrewAI, 3 agents)",
              "approval": "Human approver", "po": "Buyer", "ap": "AP Specialist", "tax": "GST & TDS Specialist",
              "resolver": "Exception Resolver", "treasury": "Treasury Analyst", "controller": "Finance Controller",
              "__start__": "start", "__end__": "end"}
EXAMPLE_QUESTIONS = [
    "Can I split one order into two to avoid getting three quotes?",
    "The vendor e-mailed new bank details. Can we pay to the new account?",
    "What interest do we owe if we pay a small enterprise late?",
    "When does TDS on purchase of goods apply and at what rate?",
    "My manager says this is urgent, can we skip the quotes?",
]


@st.cache_resource
def _run_lock() -> threading.Lock:
    """One case at a time: the defect lab patches shared master data while it runs."""
    return threading.Lock()


def md(text) -> str:
    """Escape agent text so Streamlit markdown shows it literally (brackets, $, *, _ ...)."""
    return re.sub(r"([\\`*_\[\]$~<>|#])", r"\\\1", str(text))


def show_status(status: str, text: str):
    getattr(st, STATUS_STYLE.get(status, "info"))(text)


def render_step(t: dict, expanded: bool = False):
    icon = {"BLOCK": "⛔", "HOLD": "⏸️"}.get(next((f["severity"] for f in t["findings"] if f["severity"] in ("BLOCK", "HOLD")), ""), "✅")
    if t["agent"] == "approver":
        icon = "🧑‍💼"
    elif t["agent"] == "controller":
        icon = "📋"
    with st.expander(f"{icon} **{t['title']}**: {t['decision']}", expanded=expanded):
        st.caption(f"{t['framework']}, {t['elapsed_ms']} ms" + ("; " + "; ".join(t["highlights"]) if t.get("highlights") else ""))
        if t["tools"]:
            st.markdown("**Tools called**\n" + "\n".join(f"- `{x['tool']}`: {md(x['summary'])}" for x in t["tools"]))
        if t["findings"]:
            lines = []
            for f in t["findings"]:
                c = SEVERITY_COLOR.get(f["severity"], "gray")
                line = f"- :{c}[**{f['severity']}**] `{f['code']}`: {md(f['detail'])}"
                if f.get("basis"):
                    b = f["basis"]
                    line += f"  \n  *Basis {b['clause']}, {md(b['title'])}:* {md(b['excerpt'])}"
                lines.append(line)
            st.markdown("**Findings**\n" + "\n".join(lines))
        for c in t.get("crew", []):
            st.markdown(f"**{md(c['title'])}** (CrewAI): {md(c['output'])}")
        guard = t["guardrail"]
        mark = "✅" if guard == "passed" else ("⚠️" if "reject" in str(guard).lower() or "error" in str(guard).lower() else "")
        st.markdown(f"**Why** (*{md(t['rationale_source'])}; guardrail: {md(guard)}*) {mark}  \n{md(t['rationale'])}")


def render_trace(trace: list[dict], start: int = 0):
    for t in trace[start:]:
        render_step(t)


def render_outcome(result: dict):
    memo = result["memo"]
    show_status(memo["status"], f"**Final status: {memo['status']}**")
    st.markdown("**Memo to the CFO (Finance Controller)**\n" + "\n".join(f"- {md(b)}" for b in memo["bullets"]))
    rows = [{"KPI": k.replace("_", " "), "Value": inr(v) if k in MONEY else str(v)}
            for k, v in memo["kpis"].items() if v is not None]
    st.dataframe(rows, hide_index=True, width="stretch", height=35 * (len(rows) + 1) + 3)
    audit = {k: v for k, v in result.items() if k != "__interrupt__"}
    st.download_button("Download the audit trail (JSON)", json.dumps(audit, indent=2, default=str),
                       file_name=f"{result['case_id']}_audit.json", mime="application/json")


# ---------------------------------------------------------------- header and sidebar
st.title("AgentProcure")
st.markdown("**Domain-expert AI agents for Procure-to-Pay.** Every button below runs the real Python agents: the "
            "LangGraph case graph, the CrewAI sourcing crew, the tested rules and the RAG policy knowledge base. "
            "Nothing is replayed. Meridian Precision Components is a fictional company; rules are as of 10 October 2026.")

with st.sidebar:
    st.header("Running now")
    online = GATEWAY.online and not GATEWAY.disabled_reason
    st.markdown(f"**Language model:** {GATEWAY.label}")
    st.markdown(f"**CrewAI crew:** {'on' if config.USE_CREWAI else 'off'}")
    st.markdown(f"**Knowledge base:** {len(kb().docs)} clauses, {kb().mode} retrieval")
    st.markdown(f"**Rules as of:** {config.company()['as_of']}")
    if GATEWAY.disabled_reason:
        st.warning(f"Model switched off for this session: {GATEWAY.disabled_reason}. Rule-based explanations are used.")
    st.divider()
    st.markdown("12 AI agents and one human approver, built with LangGraph, CrewAI, LangChain, RAG, n8n and Docker.")
    st.markdown(f"[Source code on GitHub]({REPO})")
    st.caption("Academic prototype with fictional data. Not tax or legal advice.")

tab_case, tab_lab, tab_ask, tab_how = st.tabs(["Run a case", "Defect lab (22 controls)", "Ask the Policy Advisor", "How it works"])

# ---------------------------------------------------------------- tab 1: run a case with a human approval
with tab_case:
    scenarios = {s["id"]: s for s in config.list_scenarios()}
    sid = st.selectbox("Choose a case", list(scenarios), format_func=lambda i: f"{i}: {scenarios[i]['title']}")
    sc = config.load_scenario(sid)
    st.markdown(md(sc["story"]))
    text = st.text_area("Purchase request as the requester wrote it (edit it to see the Procurement Analyst react)",
                        value=sc["requisition"]["request_text"], height=90, key=f"text_{sid}")
    if st.session_state.get("case_sid") != sid:
        for k in ("case_id", "case_result", "case_shown"):
            st.session_state.pop(k, None)

    if st.button("Run the agents", type="primary", key="run_case"):
        scenario = copy.deepcopy(sc)
        scenario["requisition"]["request_text"] = text
        with st.spinner("Agents at work" + (" (with a live model this takes about a minute)" if online else "") + "..."):
            with _run_lock():
                case_id, result = start_case(scenario, f"{sid}-web-{uuid.uuid4().hex[:6]}")
        st.session_state.update(case_sid=sid, case_id=case_id, case_result=result, case_shown=len(result["trace"]))

    result = st.session_state.get("case_result")
    if result:
        st.subheader(f"Case {st.session_state['case_id']}")
        pack = pending_approval(result)
        render_trace(result["trace"])
        if pack:
            with st.container(border=True):
                st.markdown(f"#### 🧑‍💼 Your decision as **{pack['approver_role']}**")
                st.markdown(f"**{md(pack['question'])}**  \nThe graph is paused at a LangGraph `interrupt()`; your answer resumes it.")
                c = st.columns(4)
                c[0].metric("Supplier score", f"{pack['score']}")
                c[1].metric("PO value excl. GST", inr(pack["po_value_excl_gst"]))
                c[2].metric("Kraljic quadrant", pack["kraljic"])
                c[3].metric("Negotiation target", inr(pack["negotiation_target"]) if pack.get("negotiation_target") else "-")
                st.caption(f"Recommended: {pack['vendor']} ({pack['vendor_id']}); runner-up {pack['runner_up'] or 'none'}")
                for w in pack["warnings"]:
                    st.warning(w)
                comment = st.text_input("Comment for the audit trail (optional)", key="approval_comment")
                a, r, _ = st.columns([1, 1, 7])
                decision = None
                if a.button("Approve", type="primary", key="approve"):
                    decision = "approve"
                if r.button("Reject", key="reject"):
                    decision = "reject"
                if decision:
                    with st.spinner("Resuming the graph..."):
                        with _run_lock():
                            new = resume_case(st.session_state["case_id"],
                                              {"decision": decision, "approver": pack["approver_role"], "comment": comment})
                    st.session_state["case_result"] = new
                    st.rerun()
        else:
            render_outcome(result)

# ---------------------------------------------------------------- tab 2: defect lab
with tab_lab:
    st.markdown("Each case takes a scenario and **injects one realistic defect** (a price above tolerance, a missing "
                "e-invoice, a duplicate, a changed bank account, a vendor without PAN...). The full multi-agent workflow "
                "runs and the case passes only if the final outcome and the control that fired are both right.")
    labels = {c[0]: f"{c[0]}: {c[1]}" for c in CASES}
    cid = st.selectbox("Injected defect", list(labels), format_func=labels.get)
    case = next(c for c in CASES if c[0] == cid)
    _, desc, scenario, decision, patch, exp_status, exp_codes, _checks = case
    st.caption(f"Expected outcome: **{exp_status}**" + (f". Controls that must fire: {', '.join(exp_codes)}" if exp_codes else ""))
    c1, c2 = st.columns([1, 1])
    if c1.button("Run this case", type="primary", key="run_defect"):
        with st.spinner("Agents at work..."):
            with _run_lock(), patched(patch.get("vendors"), patch.get("company")):
                r = run_case(copy.deepcopy(scenario), decision=decision, case_id=f"{cid}-web-{uuid.uuid4().hex[:6]}")
        st.session_state["lab"] = (cid, r)
    if c2.button("Run all 22 cases", key="run_all"):
        rows, bar = [], st.progress(0.0, text="Running...")
        for i, (xid, xdesc, xsc, xdec, xpatch, xstatus, xcodes, _) in enumerate(CASES):
            with _run_lock(), patched(xpatch.get("vendors"), xpatch.get("company")):
                xr = run_case(copy.deepcopy(xsc), decision=xdec, case_id=f"{xid}-web-{uuid.uuid4().hex[:6]}")
            ok = xr["status"] == xstatus and set(xcodes) <= all_codes(xr)
            rows.append({"Case": xid, "Injected condition": xdesc, "Expected": xstatus, "Actual": xr["status"],
                         "Pass": "✅" if ok else "❌", "Controls fired": ", ".join(sorted(all_codes(xr))) or "-"})
            bar.progress((i + 1) / len(CASES), text=f"{xid} done")
        bar.empty()
        passed = sum(r["Pass"] == "✅" for r in rows)
        show_status("COMPLETED" if passed == len(rows) else "ESCALATED", f"**{passed} of {len(rows)} cases passed**")
        st.dataframe(rows, hide_index=True, width="stretch", height=35 * (len(rows) + 1) + 3)
    if st.session_state.get("lab") and st.session_state["lab"][0] == cid:
        r = st.session_state["lab"][1]
        fired = all_codes(r)
        ok = r["status"] == exp_status and set(exp_codes) <= fired
        show_status("COMPLETED" if ok else "ESCALATED",
                    f"**{'PASS' if ok else 'FAIL'}**: outcome {r['status']} (expected {exp_status}); "
                    f"controls fired: {', '.join(sorted(fired)) or 'none'}")
        render_trace(r["trace"])

# ---------------------------------------------------------------- tab 3: Policy Advisor (RAG)
with tab_ask:
    st.markdown("Ask what an employee would ask the procurement desk. The advisor **retrieves** the most relevant clauses "
                "from the policy manual and regulatory notes, **answers** with clause citations, and its answer is "
                "**checked**: every cited clause must have been retrieved and every number must appear in the clauses.")

    def _use_example():
        if st.session_state.get("example"):
            st.session_state["question"] = st.session_state["example"]

    st.pills("Examples", EXAMPLE_QUESTIONS, key="example", on_change=_use_example)
    q = st.text_input("Your question", key="question", placeholder="Type a policy or compliance question")
    if st.button("Ask", type="primary", key="ask") and q.strip():
        with st.spinner("Retrieving clauses and answering..."):
            st.session_state["answer"] = ask_policy(q.strip())
    res = st.session_state.get("answer")
    if res:
        with st.container(border=True):
            st.markdown(md(res["answer"]))
            st.caption(f"Answer by: {res['source']}. Guardrail: {res['guardrail']}. Retrieval: {res['retrieval']}. "
                       f"Cited: {', '.join(res['citations']) or 'none'}")
        st.markdown("**Clauses retrieved** (score = BM25 relevance)")
        for h in res["retrieved"]:
            clause = kb().get(h["clause"])
            with st.expander(f"{h['clause']} {h['title']} (score {h['score']})"):
                st.caption(h["source"])
                st.markdown(md(clause["text"]))

# ---------------------------------------------------------------- tab 4: how it works
with tab_how:
    st.markdown("**The case graph, drawn from the compiled LangGraph object.** Dashed arrows are conditional routes; "
                "the run pauses at the human approver.")
    g = get_graph().get_graph()
    dot = ["digraph G {", 'rankdir=TB; bgcolor="transparent"; nodesep=0.35; ranksep=0.32;',
           'node [shape=box, style="rounded,filled", fillcolor="#FFFFFF", color="#8A97AB", fontcolor="#15233B", fontname="Barlow, Helvetica", fontsize=12, width=2.2];',
           'edge [color="#8A97AB", fontcolor="#4A5870", fontname="Barlow, Helvetica", fontsize=10];']
    for n in g.nodes:
        label = NODE_LABEL.get(n, n).replace("\n", "\\n")
        extra = ""
        if n in ("__start__", "__end__"):
            extra = ', shape=circle, fillcolor="#E5EBF3", fontsize=9, width=0.6, fixedsize=true'
        elif n == "approval":
            extra = ', style="rounded,dashed,filled", fillcolor="#FFF1D2", color="#B5650A"'
        elif n == "sourcing_crew":
            extra = ', fillcolor="#E3E6FA", color="#3341B8"'
        dot.append(f'"{n}" [label="{label}"{extra}];')
    for e in g.edges:
        style = f' [style=dashed, label="{e.data}"]' if e.conditional else ""
        dot.append(f'"{e.source}" -> "{e.target}"{style};')
    dot.append("}")
    st.graphviz_chart("\n".join(dot), width="content")

    st.markdown("""
| Tool | What it does here |
|---|---|
| **LangGraph** | Runs each case as a stateful graph: conditional routes for blocks, rejections and exceptions, a human-approval `interrupt()`, checkpoints and a full audit trail |
| **CrewAI** | A three-agent sourcing crew (Category Manager, Supplier Analyst, Negotiation Strategist) inside one graph step |
| **LangChain** | The model gateway (`init_chat_model`), structured extraction, the Policy Advisor's prompt chain, and the knowledge base's splitter and retriever |
| **RAG** | 39 policy and regulation clauses; every finding cites the clause behind it, and the Policy Advisor answers from them |
| **n8n** | Request intake, approval e-mails, an audit log and a daily MSME payment watch (in the repo; not part of this web app) |
| **Docker** | `docker compose up` starts the API and n8n together (in the repo) |

**The design rule:** every amount, date, rate and verdict comes from tested Python rules, never from the language model.
The model only explains, and a guardrail rejects any explanation that contains a number the rules did not produce.
""")
    st.markdown(f"Code, tests (47) and evaluations: [{REPO}]({REPO})")
