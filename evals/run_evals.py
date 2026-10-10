"""Control-effectiveness evaluation.

Each case mutates a base scenario (or the master data) to inject one realistic defect or
condition, and states what a competent P2P team would decide. We run the full multi-agent
workflow and score: right final outcome? right control fired? right money figure?

  python -m evals.run_evals            # prints a scorecard, writes evals/results.json and results.md
"""
from __future__ import annotations

import copy
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Run from the command line, the evaluation scores the controls (rules) offline unless EVAL_WITH_LLM=1:
# fast, repeatable, and it does not spend API quota. Importing CASES (the Streamlit app does) changes nothing.
if __name__ == "__main__" and os.getenv("EVAL_WITH_LLM") != "1":
    os.environ["LLM_PROVIDER"] = "offline"

from agentprocure import config  # noqa: E402
from agentprocure.graph import run_case  # noqa: E402


@contextmanager
def patched(vendors: dict | None = None, company: dict | None = None):
    """Temporarily change master data (vendor or company fields) for one eval case."""
    vstore, cstore = config.load_json("vendors.json")["vendors"], config.load_json("company.json")
    vbak, cbak = copy.deepcopy(vstore), copy.deepcopy(cstore)
    try:
        for vid, fields in (vendors or {}).items():
            for k, val in fields.items():
                vstore[vid][k] = val
        for k, val in (company or {}).items():
            cstore[k] = val
        yield
    finally:
        vstore.clear(); vstore.update(vbak)
        cstore.clear(); cstore.update(cbak)


def sc(sid: str, **changes) -> dict:
    s = copy.deepcopy(config.load_scenario(sid))
    for path, val in changes.items():
        node = s
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = val
    return s


S1_INV = config.load_scenario("S1")["invoice"]

CASES = [
    # id, description, scenario, decision, patch, expected status, codes that must fire, numeric checks
    ("E01", "S1 baseline: clean strategic buy", sc("S1"), None, {}, "COMPLETED", [], {"tax.tds.tds_amount": 1774}),
    ("E02", "Invoice price +0.8% (inside 1% tolerance)",
     sc("S1", invoice__lines=[{"hsn": "7616", "qty": 4000, "unit_price": 441.5}], invoice__igst=321840.0, invoice__total=2109840.0),
     None, {}, "COMPLETED", [], {}),
    ("E03", "Invoice price +1.5% (outside tolerance)",
     sc("S1", invoice__lines=[{"hsn": "7616", "qty": 4000, "unit_price": 444.57}], invoice__igst=324050.4, invoice__total=2124330.4),
     None, {}, "COMPLETED_WITH_HOLD", ["PRICE_VARIANCE"], {"ap.match.approved_total": 2093320.0}),
    ("E04", "Large supplier invoice without IRN", sc("S1", invoice__irn=None, invoice__irn_date=None),
     None, {}, "ON_HOLD", ["IRN_MISSING"], {}),
    ("E05", "IRN generated 35 days after invoice date", sc("S1", invoice__date="2026-08-27", invoice__irn_date="2026-10-01"),
     None, {}, "ON_HOLD", ["IRN_LATE"], {}),
    ("E06", "Inter-state invoice billed as CGST+SGST", sc("S1", invoice__igst=0, invoice__cgst=159660.0, invoice__sgst=159660.0),
     None, {}, "ON_HOLD", ["WRONG_TAX_TYPE"], {}),
    ("E07", "Same invoice already booked (number formatted differently)",
     sc("S1", invoice_history=[{"vendor_id": "V-102", "invoice_no": "TAC-26-27-4417", "date": "2026-10-01", "total": 2093320.0}]),
     None, {}, "ON_HOLD", ["DUPLICATE_INVOICE"], {}),
    ("E08", "Bank account on invoice differs from master", sc("S1", invoice__bank_account_masked="XXXXXX1111"),
     None, {}, "ON_HOLD", ["BANK_ON_INVOICE_DIFFERS"], {}),
    ("E09", "CFO rejects at approval", sc("S1"), {"decision": "reject", "comment": "Defer"}, {}, "REJECTED", [], {}),
    ("E10", "Only two quotes for a Rs 19 lakh buy", sc("S1", quotes=config.load_scenario("S1")["quotes"][:2]),
     None, {}, "ESCALATED", ["QUOTES_INSUFFICIENT"], {}),
    ("E11", "Cost center budget nearly exhausted", sc("S1"), None,
     {"company": {"budgets": {**config.company()["budgets"], "CC-PRD-210": {"name": "Production - Die-casting line", "fy_budget": 25000000, "consumed": 23000000, "committed": 1000000}}}},
     "ESCALATED", ["BUDGET_EXCEEDED"], {}),
    ("E12", "S2 baseline: price variance + QC rejection", sc("S2"), None, {}, "COMPLETED_WITH_HOLD",
     ["PRICE_VARIANCE", "QTY_EXCEEDS_ACCEPTED"], {"ap.match.disputed_total": 67059.40}),
    ("E13", "S2 with correct price and no rejection",
     sc("S2", invoice__lines=[{"hsn": "8483", "qty": 2500, "unit_price": 284.0}], invoice__igst=127800.0, invoice__total=837800.0,
        grn__accepted_qty=2500, grn__rejected_qty=0),
     None, {}, "COMPLETED", [], {"ap.match.approved_total": 837800.0}),
    ("E14", "Invoice arrives with no goods receipt", sc("S2", grn=None), None, {}, "ON_HOLD", ["MISSING_GRN"], {}),
    ("E15", "S3 baseline: split purchase + vendor red flags", sc("S3"), None, {}, "ESCALATED",
     ["GSTIN_CHECKSUM_INVALID", "PAN_MISMATCH", "BANK_CHANGE_UNVERIFIED", "SPLIT_PURCHASE_SUSPECTED"], {}),
    ("E16", "S3 after vendor KYC is fixed: split purchase alone still blocks", sc("S3"), None,
     {"vendors": {"V-105": {"gstin": "06AAHCV3317L1Z5", "bank": {"account_masked": "XXXXXX9015", "changed_on": "2026-10-04", "change_verified": True}}}},
     "ESCALATED", ["SPLIT_PURCHASE_SUSPECTED"], {}),
    ("E17", "S4 baseline: TDS threshold crossing + overdue MSME invoice", sc("S4"), None, {}, "COMPLETED", ["MSME_OVERDUE"],
     {"tax.tds.tds_amount": 480}),
    ("E18", "S4 supplier still below Rs 50 lakh for the year", sc("S4"), None,
     {"vendors": {"V-106": {"purchases_ty_to_date": 3_000_000}}}, "COMPLETED", [], {"tax.tds.tds_amount": 0}),
    ("E19", "S4 supplier without PAN on record (5% TDS rate)", sc("S4"), None,
     {"vendors": {"V-106": {"pan": None}}}, "COMPLETED", ["PAN_NOT_ON_MASTER", "TDS_HIGHER_RATE_NO_PAN"], {"tax.tds.tds_amount": 24000}),
    ("E20", "S4 with no overdue MSME items", sc("S4", open_payables=[]), None, {}, "COMPLETED", [], {"memo.kpis.msme_interest_accrued": 0.0}),
    ("E21", "Early-payment discount worth more than cost of funds", sc("S1"), None,
     {"vendors": {"V-102": {"terms": {"payment_days": 60, "written_agreement": True, "discount": {"pct": 2.0, "days": 15}}}}},
     "COMPLETED", [], {"treasury.plan.take_discount": True}),
    ("E22", "Medium enterprise is outside the MSMED 45-day rule", sc("S2"), None, {}, "COMPLETED_WITH_HOLD", [],
     {"treasury.plan.msme.covered": False}),
]


def dig(d, path):
    for k in path.split("."):
        d = d[k]
    return d


def all_codes(result: dict) -> set[str]:
    return {f["code"] for t in result.get("trace", []) for f in t.get("findings", [])}


def run():
    rows = []
    for cid, desc, scenario, decision, patch, exp_status, exp_codes, checks in CASES:
        with patched(patch.get("vendors"), patch.get("company")):
            r = run_case(scenario, decision=decision, case_id=f"{cid}-eval")
        codes = all_codes(r)
        status_ok = r["status"] == exp_status
        codes_ok = set(exp_codes) <= codes
        num_ok = True
        num_detail = []
        for path, want in checks.items():
            try:
                got = dig(r, path)
            except (KeyError, TypeError):
                got = None
            ok = (abs(got - want) < 0.01) if isinstance(want, (int, float)) and not isinstance(want, bool) and got is not None else got == want
            num_ok &= ok
            num_detail.append(f"{path}={got}")
        rows.append({"id": cid, "case": desc, "expected": exp_status, "actual": r["status"], "status_ok": status_ok,
                     "controls_expected": exp_codes, "controls_fired": sorted(codes), "controls_ok": codes_ok,
                     "values_ok": num_ok, "values": num_detail, "pass": status_ok and codes_ok and num_ok})
    return rows


def main():
    rows = run()
    passed = sum(r["pass"] for r in rows)
    out = Path(__file__).parent
    (out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    md = ["| ID | Case | Expected | Actual | Controls | Values | Pass |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['case']} | {r['expected']} | {r['actual']} | {'ok' if r['controls_ok'] else 'MISS'} | "
                  f"{'ok' if r['values_ok'] else 'MISS'} | {'PASS' if r['pass'] else 'FAIL'} |")
    md.append(f"\n**{passed}/{len(rows)} cases passed ({passed / len(rows):.0%}).**")
    (out / "results.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    for r in rows:
        if not r["pass"]:
            print("FAIL", r["id"], r["actual"], r["controls_fired"], r["values"])
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
