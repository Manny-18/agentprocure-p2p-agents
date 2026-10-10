"""Build web/index.html (the live demo) from the exported traces, eval results and business case.

  python -m agentprocure.export_traces --out web/traces.json
  python -m evals.run_evals
  python web/build_demo.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentprocure.agents.personas import PERSONAS  # noqa: E402
from agentprocure.business_case import evaluate  # noqa: E402
from agentprocure.knowledge import kb  # noqa: E402

WEB = ROOT / "web"


def slim_step(t: dict) -> dict:
    keep = {k: t.get(k) for k in ("agent", "title", "framework", "mandate", "decision", "highlights", "rationale",
                                   "rationale_source", "guardrail", "elapsed_ms", "engine", "crew_tool_calls", "email_draft")}
    keep["tools"] = [{"tool": x["tool"], "summary": x["summary"]} for x in t.get("tools", [])]
    keep["findings"] = [{"code": f["code"], "severity": f["severity"], "detail": f["detail"],
                         "basis": (f.get("basis") or {}).get("clause"), "basis_title": (f.get("basis") or {}).get("title")}
                        for f in t.get("findings", [])]
    if t.get("crew"):
        keep["crew"] = [{"agent": c["agent"], "title": c["title"], "output": c["output"]} for c in t["crew"]]
    return {k: v for k, v in keep.items() if v not in (None, [], "")}


def slim_case(c: dict) -> dict:
    d = c["data"]
    out = {"id": c["id"], "title": c["title"], "story": c["story"], "learning_points": c["learning_points"],
           "request_text": c["request_text"], "status": c["status"], "approval_pack": c["approval_pack"],
           "pre": c["steps_before_approval"], "steps": [slim_step(t) for t in c["trace"]],
           "memo": d.get("memo"), "pr": {k: d["requisition"][k] for k in ("pr_no", "requester", "department", "cost_center", "estimated_value")}}
    out["pr"]["item"] = d["requisition"]["item"]
    if d.get("sourcing"):
        s = d["sourcing"]
        out["kraljic"] = {k: s["kraljic"][k] for k in ("quadrant", "annual_spend", "profit_impact", "supply_risk", "supply_risk_score", "weights")}
        out["ranking"] = [{k: r[k] for k in ("vendor_id", "vendor", "unit_price", "landed_unit_cost", "lead_time_days", "msme",
                                             "scores", "weighted_total", "eligible", "note")} for r in s["scorecard"]["ranking"]]
        out["should_cost"] = s["negotiation"].get("should_cost")
    if d.get("po"):
        po = d["po"]
        out["po"] = {"po_no": po["po_no"], "vendor": po["vendor"], "taxable": po["taxable"], "tax_type": po["tax"]["tax_type"],
                     "tax_total": po["tax"]["tax_total"], "total": po["tax"]["invoice_total"], "delivery_by": po["delivery_by"], "terms": po["terms"]}
    if d.get("ap"):
        out["match"] = d["ap"]["match"]
    if d.get("tax"):
        t = d["tax"]
        out["tax"] = {"tds": {k: t["tds"][k] for k in ("tds_amount", "base", "rate_pct", "reason", "provision")},
                      "itc_amount": t["itc_amount"], "itc_on_hold": t["itc_on_hold"], "tax_type": t["gst"]["expected"]["tax_type"],
                      "rate_pct": t["gst"]["expected"]["rate_pct"]}
    if d.get("treasury"):
        tr = d["treasury"]
        out["treasury"] = {"net_payable": tr["net_payable"], "due_date": tr["plan"]["due_date"], "pay_on": tr["plan"]["pay_on"],
                           "discount": tr["plan"]["discount"], "msme": tr["plan"]["msme"], "reasons": tr["plan"]["reasons"],
                           "alerts": tr["alerts"], "run": tr["payment_run"]}
    return out


def main():
    traces = json.loads((WEB / "traces.json").read_text(encoding="utf-8"))
    evals = json.loads((ROOT / "evals" / "results.json").read_text(encoding="utf-8"))
    bc = evaluate()
    personas = {k: {"title": v["title"], "framework": v["framework"], "mandate": v["mandate"], "expertise": v["expertise"]}
                for k, v in PERSONAS.items()}
    data = {"as_of": traces["as_of"], "generated_with": traces["generated_with"],
            "company": {k: traces["company"][k] for k in ("name", "plant", "industry", "gstin", "cost_of_funds_pct", "rbi_bank_rate_pct", "tax_year")},
            "cases": {k: slim_case(c) for k, c in traces["cases"].items()},
            "personas": personas,
            "evals": [{k: r[k] for k in ("id", "case", "expected", "actual", "pass")} for r in evals],
            "business_case": {k: bc[k] for k in ("Conservative", "Base", "Optimistic")},
            "ops_kpis": bc["operational_kpis"]}
    data["kb"] = [{"clause": d.metadata["clause"], "title": d.metadata["title"], "section": d.metadata["section"],
                   "source": d.metadata["source"], "text": d.page_content} for d in kb().docs]
    rag = json.loads((ROOT / "evals" / "rag_results.json").read_text(encoding="utf-8"))
    data["rag_eval"] = {k: rag[k] for k in ("retrieval", "questions", "hit_at_1", "hit_at_3", "mrr")}
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = (WEB / "demo_template.html").read_text(encoding="utf-8")
    html = html.replace("/*__RULES__*/", (WEB / "rules.js").read_text(encoding="utf-8"))
    html = html.replace("__DATA_JSON__", payload)
    (WEB / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote web/index.html ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
