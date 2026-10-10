"""Unit tests for the deterministic domain rules (the 'expert knowledge' the agents rely on)."""
import pytest

from agentprocure import config
from agentprocure.llm import numbers_grounded
from agentprocure.rules.gst import (check_invoice_tax, compute_tax, einvoice_check, gstin_checksum,
                                    tax_type, validate_gstin)
from agentprocure.rules.matching import bank_change_check, duplicate_check, three_way_match
from agentprocure.rules.msme import disallowance_exposure, msme_due_date, msme_interest
from agentprocure.rules.policy import approver_for, check_requisition, quote_rule
from agentprocure.rules.sourcing import WEIGHTS, kraljic, scorecard, should_cost
from agentprocure.rules.tds import tds_on_goods
from agentprocure.rules.treasury import discount_apr


# ------------------------------------------------------------------ GST
@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "29AABCT8834R1ZD", "27AAKCM4821Q1ZU"])
def test_gstin_checksum_valid(gstin):
    assert gstin_checksum(gstin[:14]) == gstin[14]
    assert validate_gstin(gstin)["issues"] == []


def test_gstin_bad_checksum_and_pan_mismatch():
    v = config.vendors()["V-105"]
    res = validate_gstin(v["gstin"], v["pan"])
    codes = {i["code"] for i in res["issues"]}
    assert {"GSTIN_CHECKSUM_INVALID", "PAN_MISMATCH"} <= codes


def test_gstin_format():
    assert validate_gstin("27AAKCM4821Q1Z")["issues"][0]["code"] == "GSTIN_FORMAT_INVALID"
    assert validate_gstin(None)["issues"][0]["code"] == "GSTIN_MISSING"


def test_tax_type_and_split():
    assert tax_type("27", "27") == "CGST+SGST"
    assert tax_type("29", "27") == "IGST"
    t = compute_tax(860000, 18, "27", "27")
    assert (t["cgst"], t["sgst"], t["igst"], t["invoice_total"]) == (77400.0, 77400.0, 0.0, 1014800.0)


def test_invoice_tax_clean_for_s1():
    s = config.load_scenario("S1")
    v = config.vendors()["V-102"]
    out = check_invoice_tax(s["invoice"], v, config.company(), config.hsn_rates())
    assert out["issues"] == []
    assert out["expected"]["igst"] == 319320.0


def test_wrong_tax_type_detected():
    s = config.load_scenario("S1")
    inv = dict(s["invoice"], igst=0, cgst=159660.0, sgst=159660.0)
    out = check_invoice_tax(inv, config.vendors()["V-102"], config.company(), config.hsn_rates())
    assert "WRONG_TAX_TYPE" in {i["code"] for i in out["issues"]}


def test_einvoice_rules():
    v_big, v_small = config.vendors()["V-102"], config.vendors()["V-106"]
    inv = {"date": "2026-10-01", "irn": None, "irn_date": None}
    assert einvoice_check(inv, v_big)["issues"][0]["code"] == "IRN_MISSING"
    assert einvoice_check(inv, v_small)["required"] is False
    late = {"date": "2026-08-01", "irn": "x", "irn_date": "2026-09-05"}
    assert einvoice_check(late, v_big)["issues"][0]["code"] == "IRN_LATE"


# ------------------------------------------------------------------ TDS (Income-tax Act 2025 s.393, old 194Q)
def test_tds_below_threshold():
    r = tds_on_goods(buyer_prev_turnover_cr=420, seller_pan="X", cumulative_before=3_800_000, this_taxable=675_920)
    assert r["tds_amount"] == 0 and not r["applicable"]


def test_tds_crossing_threshold_only_excess():
    r = tds_on_goods(buyer_prev_turnover_cr=420, seller_pan="X", cumulative_before=4_620_000, this_taxable=860_000)
    assert r["base"] == 480_000 and r["tds_amount"] == 480


def test_tds_already_crossed_full_value():
    r = tds_on_goods(buyer_prev_turnover_cr=420, seller_pan="X", cumulative_before=11_200_000, this_taxable=1_774_000)
    assert r["tds_amount"] == 1774


def test_tds_no_pan_and_small_buyer():
    assert tds_on_goods(buyer_prev_turnover_cr=420, seller_pan=None, cumulative_before=5_000_000,
                        this_taxable=100_000)["tds_amount"] == 5000
    assert tds_on_goods(buyer_prev_turnover_cr=8, seller_pan="X", cumulative_before=9e6, this_taxable=1e6)["tds_amount"] == 0


# ------------------------------------------------------------------ MSMED Act
def test_msme_due_dates():
    assert msme_due_date(acceptance_date="2026-08-28", category="micro", written_agreement=True, agreed_days=30)["due_date"] == "2026-09-27"
    assert msme_due_date(acceptance_date="2026-10-01", category="small", written_agreement=True, agreed_days=60)["due_date"] == "2026-11-15"
    assert msme_due_date(acceptance_date="2026-10-01", category="small", written_agreement=False, agreed_days=60)["due_date"] == "2026-10-16"
    assert msme_due_date(acceptance_date="2026-10-01", category="medium", written_agreement=True, agreed_days=45)["covered"] is False


def test_msme_interest_compound_3x_bank_rate():
    r = msme_interest(principal=755200, due_date="2026-09-27", as_of="2026-10-10", bank_rate_pct=5.75)
    assert r["annual_rate_pct"] == 17.25 and r["late_days"] == 13
    assert 4500 < r["interest"] < 4700


def test_disallowance():
    assert disallowance_exposure(amount=640000, due_date="2026-09-27", tax_year_end="2027-03-31", paid=False)["amount_at_risk"] == 640000
    assert disallowance_exposure(amount=640000, due_date="2026-09-27", tax_year_end="2027-03-31", paid=True)["at_risk"] is False


# ------------------------------------------------------------------ AP controls
def test_three_way_match_s2_numbers():
    s = config.load_scenario("S2")
    m = three_way_match(po={"unit_price": 284.0, "qty": 2500, "freight": 0}, grn=s["grn"], invoice=s["invoice"],
                        tolerance=config.company()["match_tolerance"], tax_rate_pct=18)
    assert {e["code"] for e in m["exceptions"]} == {"PRICE_VARIANCE", "QTY_EXCEEDS_ACCEPTED"}
    assert m["approved_total"] == 797585.60
    assert m["disputed_total"] == 67059.40


def test_price_within_tolerance_is_matched():
    s = config.load_scenario("S1")
    inv = dict(s["invoice"], lines=[{"hsn": "7616", "qty": 4000, "unit_price": 441.5}])
    m = three_way_match(po={"unit_price": 438.0, "qty": 4000, "freight": 22000}, grn=s["grn"], invoice=inv,
                        tolerance=config.company()["match_tolerance"], tax_rate_pct=18)
    assert m["status"] == "MATCHED"


def test_duplicate_detection_normalises_numbers():
    inv = {"vendor_id": "V-1", "invoice_no": "INV/26-27/0042", "date": "2026-10-01", "total": 1000}
    hist = [{"vendor_id": "V-1", "invoice_no": "inv-26-27-42", "date": "2026-09-30", "total": 1000}]
    assert duplicate_check(inv, hist)["issues"][0]["code"] == "DUPLICATE_INVOICE"


def test_bank_change_cooling_period():
    v = config.vendors()["V-105"]
    assert bank_change_check(v, None, "2026-10-10", 30)["issues"][0]["code"] == "BANK_CHANGE_UNVERIFIED"
    assert bank_change_check(v, None, "2026-12-10", 30)["issues"] == []


# ------------------------------------------------------------------ policy
def test_doa_and_quote_bands():
    co = config.company()
    assert approver_for(150000, co["doa"]) == "Department Head"
    assert approver_for(710000, co["doa"]) == "Plant Head"
    assert approver_for(1774000, co["doa"]) == "CFO"
    assert approver_for(12500000, co["doa"]) == "Managing Director"
    assert quote_rule(2600000, co["quote_rules"])["rfq_required"] is True


def test_s3_policy_blocks():
    s = config.load_scenario("S3")
    res = check_requisition(s["requisition"], s["quotes"], config.vendors(), config.company(), s["pr_history"])
    codes = {f["code"] for f in res["findings"] if f["severity"] == "BLOCK"}
    assert res["decision"] == "BLOCK"
    assert set(s["expected"]["blocking_codes"]) <= codes


def test_s1_policy_clears():
    s = config.load_scenario("S1")
    res = check_requisition(s["requisition"], s["quotes"], config.vendors(), config.company(), [])
    assert res["decision"] == "PROCEED" and res["approver"] == "CFO"


# ------------------------------------------------------------------ sourcing
def test_weights_sum_to_one():
    for w in WEIGHTS.values():
        assert abs(sum(w.values()) - 1) < 1e-9


def test_s1_cheapest_loses():
    s = config.load_scenario("S1")
    k = kraljic(annual_spend=21_088_000, qualified_suppliers=3, lead_time_days=24.7, criticality="high")
    assert k["quadrant"] == "Strategic"
    sc = scorecard(quotes=s["quotes"], vendors=config.vendors(), qty=4000, weights=k["weights"])
    assert sc["recommended"]["vendor_id"] == "V-102"
    assert sc["cheapest"]["vendor_id"] == "V-103"


def test_infeasible_lead_time_excluded():
    s = config.load_scenario("S2")
    sc = scorecard(quotes=s["quotes"], vendors=config.vendors(), qty=2500, weights=WEIGHTS["Leverage"], infeasible=["V-109"])
    assert sc["recommended"]["vendor_id"] == "V-104"
    assert next(r for r in sc["ranking"] if r["vendor_id"] == "V-109")["eligible"] is False


def test_should_cost():
    r = should_cost({"material_kg": 0.95, "material_rate_per_kg": 238, "conversion": 120, "secondary_ops": 40,
                     "overhead_margin_pct": 12}, 438, 4000, 48000)
    assert r["should_cost"] == 432.43 and r["verdict"] == "negotiate"


# ------------------------------------------------------------------ treasury
def test_discount_apr():
    assert discount_apr(1.0, 15, 60) == 8.19      # below 9.25% cost of funds -> skip
    assert discount_apr(1.5, 10, 45) == 15.88     # above -> take


# ------------------------------------------------------------------ guardrail
def test_guardrail_flags_invented_numbers():
    facts = {"approved_total": 797585.6, "rate_pct": 18, "disputed": 67059.4}
    ok, _ = numbers_grounded("Pay Rs 7,97,585.60 now; hold Rs 67,059.40 at 18% GST.", facts)
    assert ok
    ok, bad = numbers_grounded("Pay Rs 8,10,000 and expect a 5% discount.", facts)
    assert not ok and len(bad) == 2


# ------------------------------------------------------------------ LLM gateway resilience
def test_gateway_retries_rate_limit_then_succeeds(monkeypatch):
    from agentprocure import config as cfg
    from agentprocure.llm import LLMGateway

    class GoogleRateLimitError(Exception):
        pass

    class FakeChat:
        def __init__(self):
            self.n = 0

        def invoke(self, _messages):
            self.n += 1
            if self.n == 1:
                raise GoogleRateLimitError("429 RESOURCE_EXHAUSTED")
            return type("Msg", (), {"content": "Pay Rs 7,97,585.60 on time."})()

    monkeypatch.setattr(cfg, "LLM_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(cfg, "LLM_RETRY_WAIT_S", 0)
    g = LLMGateway(provider="gemini", model="test-model")
    g._chat = FakeChat()
    out = g.narrate(persona="p", task="t", facts={"approved_total": 797585.6}, fallback="fallback")
    assert out["guardrail"] == "passed" and g.retries == 1


def test_gateway_does_not_retry_auth_errors(monkeypatch):
    from agentprocure import config as cfg
    from agentprocure.llm import LLMGateway

    class GooglePermissionDeniedError(Exception):
        pass

    class DeniedChat:
        def invoke(self, _messages):
            raise GooglePermissionDeniedError("403 PERMISSION_DENIED")

    monkeypatch.setattr(cfg, "LLM_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(cfg, "LLM_RETRY_WAIT_S", 0)
    g = LLMGateway(provider="gemini", model="test-model")
    g._chat = DeniedChat()
    out = g.narrate(persona="p", task="t", facts={}, fallback="fallback text")
    assert out["text"] == "fallback text" and "access denied" in out["guardrail"] and g.retries == 0


def test_gateway_stops_calling_after_daily_quota(monkeypatch):
    from agentprocure import config as cfg
    from agentprocure.llm import LLMGateway

    class GoogleRateLimitError(Exception):
        pass

    class QuotaChat:
        def __init__(self):
            self.n = 0

        def invoke(self, _messages):
            self.n += 1
            raise GoogleRateLimitError("429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")

    monkeypatch.setattr(cfg, "LLM_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(cfg, "LLM_RETRY_WAIT_S", 0)
    g = LLMGateway(provider="gemini", model="test-model")
    chat = QuotaChat()
    g._chat = chat
    first = g.narrate(persona="p", task="t", facts={}, fallback="fb")
    second = g.narrate(persona="p", task="t", facts={}, fallback="fb")
    assert chat.n == 1 and g.retries == 0                      # no retries, and no second call
    assert "daily free-tier quota" in first["guardrail"] and "daily free-tier quota" in second["guardrail"]
