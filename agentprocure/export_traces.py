"""Export full agent traces for every scenario as JSON (used by the web demo and the report).

  python -m agentprocure.export_traces --out web/traces.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .graph import pending_approval, resume_case, start_case
from .llm import GATEWAY


def export_case(sid: str, decision: dict) -> dict:
    sc = config.load_scenario(sid)
    case_id, first = start_case(sc, f"{sid}-web-{decision['decision']}")
    pack = pending_approval(first)
    pre = len(first["trace"])
    final = resume_case(case_id, decision) if pack else first
    keep = {}
    for key in ("requisition", "policy", "sourcing", "approval", "po", "ap", "tax", "resolution", "treasury", "memo"):
        if key in final:
            keep[key] = final[key]
    if "requisition" in keep:
        keep["requisition"] = {k: v for k, v in keep["requisition"].items() if k != "parsed"} | {"parsed": final["requisition"]["parsed"]}
    return {"id": sc["id"], "title": sc["title"], "story": sc["story"], "learning_points": sc["learning_points"],
            "request_text": sc["requisition"]["request_text"], "case_id": case_id, "approval_pack": pack,
            "steps_before_approval": pre, "trace": final["trace"], "status": final["status"], "data": keep}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="web/traces.json")
    args = ap.parse_args(argv)
    approve = {"decision": "approve", "comment": "Approved as recommended."}
    cases = {s["id"]: export_case(s["id"], approve) for s in config.list_scenarios()}
    reasons = {"S1": "Defer: Q3 volume forecast is under review.", "S2": "Hold: re-quote after the drawing revision.",
               "S4": "Use existing stock first; re-raise next week."}
    for sid, why in reasons.items():
        cases[f"{sid}-reject"] = export_case(sid, {"decision": "reject", "comment": why})
    payload = {"generated_with": GATEWAY.label, "as_of": config.company()["as_of"], "company": config.company(),
               "vendors": config.vendors(), "cases": cases}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) for {len(cases)} cases")


if __name__ == "__main__":
    main()
