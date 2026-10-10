"""Tests for the policy knowledge base (RAG), the Policy Advisor and clause citations on findings."""
from fastapi.testclient import TestClient

from agentprocure import config
from agentprocure.agents.advisor import ask_policy
from agentprocure.api import app
from agentprocure.graph import run_case
from agentprocure.knowledge import CODE_TO_CLAUSE, kb
from evals.rag_eval import run as run_rag_eval


def test_every_clause_is_a_document_with_unique_id():
    ids = [d.metadata["clause"] for d in kb().docs]
    assert len(ids) == len(set(ids)) >= 35
    assert {"POL-4.2", "POL-5.2", "REG-MSMED-2", "REG-IT-2", "REG-GST-4"} <= set(ids)


def test_every_finding_code_maps_to_a_real_clause():
    missing = {code: cid for code, cid in CODE_TO_CLAUSE.items() if kb().get(cid) is None}
    assert not missing


def test_retrieval_quality_meets_target():
    res = run_rag_eval()
    assert res["hit_at_3"] >= 0.9 and res["hit_at_1"] >= 0.8


def test_policy_advisor_cites_the_right_clause_offline():
    res = ask_policy("Can I split one order into two smaller orders to avoid getting three quotes?")
    assert "POL-4.2" in res["citations"] and res["source"].startswith("extractive")
    assert "POL-4.2" in {r["clause"] for r in res["retrieved"]}


def test_findings_carry_their_policy_basis():
    r = run_case(config.load_scenario("S3"), case_id="S3-rag-test")
    policy_step = next(t for t in r["trace"] if t["agent"] == "policy")
    basis = {f["code"]: f["basis"]["clause"] for f in policy_step["findings"] if f.get("basis")}
    assert basis["SPLIT_PURCHASE_SUSPECTED"] == "POL-4.2"
    assert basis["BANK_CHANGE_UNVERIFIED"] == "POL-5.2"
    assert basis["GSTIN_CHECKSUM_INVALID"] == "REG-GST-3"


def test_analyst_retrieves_reminders_for_urgent_sole_source_request():
    r = run_case(config.load_scenario("S3"), case_id="S3-rag-reminders")
    clauses = {x["clause"] for x in r["requisition"]["policy_reminders"]}
    assert {"POL-3.3", "POL-4.3"} <= clauses


def test_policy_ask_endpoint():
    res = TestClient(app).post("/policy/ask", json={"question": "Can we pay a vendor whose bank details changed by e-mail?"})
    assert res.status_code == 200 and "POL-5.2" in res.json()["citations"]
