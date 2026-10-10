"""End-to-end tests of the LangGraph workflow (with the CrewAI crew) against each scenario's
expected outcome, plus the human-in-the-loop interrupt and the rejection path."""
import pytest

from agentprocure import config
from agentprocure.graph import pending_approval, resume_case, run_case, start_case


@pytest.fixture(scope="module")
def results():
    return {sid: run_case(config.load_scenario(sid), case_id=f"{sid}-pytest") for sid in ("S1", "S2", "S3", "S4")}


def test_final_statuses(results):
    for sid, r in results.items():
        exp = config.load_scenario(sid)["expected"]
        assert r["status"] == exp["final_status"], sid


def test_s1_outcomes(results):
    r, exp = results["S1"], config.load_scenario("S1")["expected"]
    assert r["sourcing"]["recommended_vendor"] == exp["vendor"]
    assert r["approval"]["approver_role"] == exp["approver"]
    assert r["tax"]["tds"]["tds_amount"] == exp["tds_amount"]
    assert r["treasury"]["plan"]["pay_on"] == exp["pay_on"]
    assert r["treasury"]["plan"]["take_discount"] is exp["take_discount"]
    assert r["memo"]["kpis"]["touchless_invoice"] is True


def test_s2_outcomes(results):
    r, exp = results["S2"], config.load_scenario("S2")["expected"]
    assert {f["code"] for f in r["ap"]["findings"]} == set(exp["exceptions"])
    assert r["ap"]["match"]["approved_total"] == exp["approved_payable"]
    assert r["ap"]["match"]["disputed_total"] == exp["disputed_amount"]
    assert r["resolution"]["credit_note"]["total"] == exp["disputed_amount"]
    assert r["tax"]["tds"]["tds_amount"] == exp["tds_amount"]
    assert r["approval"]["approver_role"] == exp["approver"]


def test_s3_never_reaches_sourcing(results):
    r = results["S3"]
    assert "sourcing" not in r and "po" not in r
    assert [t["agent"] for t in r["trace"]] == ["intake", "policy", "controller"]


def test_s4_outcomes(results):
    r, exp = results["S4"], config.load_scenario("S4")["expected"]
    assert r["tax"]["tds"]["tds_amount"] == exp["tds_amount"]
    assert r["treasury"]["plan"]["msme"]["due_date"] == exp["msme_due"]
    overdue = [a["invoice_no"] for a in r["treasury"]["alerts"] if a["severity"] == "CRITICAL"]
    assert overdue == exp["overdue_msme_invoices"]


def test_crew_used_its_tools(results):
    crew_step = next(t for t in results["S1"]["trace"] if t["agent"] == "supplier_analyst")
    assert crew_step["crew_tool_calls"] == ["kraljic_analysis", "supplier_scorecard", "should_cost_model"]
    assert crew_step["engine"].startswith("CrewAI")


def test_interrupt_then_reject():
    case_id, first = start_case(config.load_scenario("S1"), "S1-reject-test")
    pack = pending_approval(first)
    assert pack and pack["approver_role"] == "CFO" and pack["vendor_id"] == "V-102"
    final = resume_case(case_id, {"decision": "reject", "approver": "CFO", "comment": "Defer"})
    assert final["status"] == "REJECTED" and "po" not in final
