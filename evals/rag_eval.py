"""Retrieval evaluation for the policy knowledge base (RAG).

Each question is phrased the way an employee would ask it, not in the policy's own words. A question is a
hit when one of its acceptable clauses is ranked first (hit@1) or within the top three (hit@3).

  python -m evals.rag_eval          # prints the table, writes evals/rag_results.json and rag_results.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentprocure.knowledge import kb  # noqa: E402

QUESTIONS = [
    ("Can I split one order into two smaller orders to avoid getting three quotes?", {"POL-4.2"}),
    ("How many quotations do I need for a purchase of Rs 4 lakh?", {"POL-4.1"}),
    ("Who must approve a purchase order worth Rs 60 lakh?", {"POL-2.1"}),
    ("The vendor emailed new bank account details. Can we pay to the new account?", {"POL-5.2"}),
    ("Is 'we have worked with them before' a good enough reason to buy from one supplier only?", {"POL-4.3"}),
    ("The invoice price is slightly higher than the PO price. Can we still pay it?", {"POL-7.1"}),
    ("Should we stop the whole invoice when only part of it is disputed?", {"POL-7.2"}),
    ("When should we take an early payment discount?", {"POL-8.2"}),
    ("Within how many days must a micro enterprise supplier be paid?", {"REG-MSMED-1", "POL-8.3"}),
    ("What interest do we owe if we pay a small enterprise late?", {"REG-MSMED-2"}),
    ("When does TDS on purchase of goods apply and at what rate?", {"REG-IT-2"}),
    ("What happens to our tax deduction if MSME dues are still unpaid at year end?", {"REG-IT-3"}),
    ("When is an e-invoice IRN mandatory for a supplier?", {"REG-GST-4"}),
    ("When should a supplier charge IGST instead of CGST and SGST?", {"REG-GST-2"}),
    ("Can we keep the input tax credit if we have not paid the supplier for 200 days?", {"REG-GST-5", "POL-7.4"}),
    ("The vendor has no PAN. Do we still pay and what TDS rate applies?", {"POL-5.3", "REG-IT-2"}),
    ("What is the current RBI Bank Rate used for MSME late-payment interest?", {"REG-RBI-1"}),
    ("Does the 45-day payment rule apply to medium enterprises or traders?", {"REG-MSMED-4"}),
    ("My manager says this is urgent, can we skip the quotes?", {"POL-3.3"}),
    ("How do we check that a GSTIN is genuine?", {"REG-GST-3", "POL-5.1"}),
    ("Can the buyer who negotiated the deal also approve the PO?", {"POL-2.3"}),
    ("Is the cheapest quote always the one we should pick?", {"POL-4.4"}),
]


def run(k: int = 3) -> dict:
    base = kb()
    rows, hit1, hit3, rr = [], 0, 0, 0.0
    for q, expected in QUESTIONS:
        got = [r["clause"] for r in base.retrieve(q, k=k)]
        rank = next((i + 1 for i, c in enumerate(got) if c in expected), None)
        hit1 += rank == 1
        hit3 += rank is not None
        rr += 1 / rank if rank else 0
        rows.append({"question": q, "expected": sorted(expected), "retrieved": got, "rank": rank})
    n = len(QUESTIONS)
    return {"retrieval": base.mode, "questions": n, "hits_at_1": hit1, "hits_at_3": hit3,
            "hit_at_1": round(hit1 / n, 3), "hit_at_3": round(hit3 / n, 3), "mrr": round(rr / n, 3), "rows": rows}


def main():
    res = run()
    out = Path(__file__).parent
    (out / "rag_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    n = res["questions"]
    md = [f"Retrieval: {res['retrieval']} | {n} questions | hit@1 {res['hits_at_1']}/{n} ({res['hits_at_1'] / n:.1%}) | "
          f"hit@3 {res['hits_at_3']}/{n} ({res['hits_at_3'] / n:.1%}) | MRR {res['mrr']}", "", "| Question | Expected | Retrieved (top 3) | Rank |", "|---|---|---|---|"]
    md += [f"| {r['question']} | {', '.join(r['expected'])} | {', '.join(r['retrieved'])} | {r['rank'] or 'miss'} |" for r in res["rows"]]
    (out / "rag_results.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0 if res["hit_at_3"] >= 0.9 else 1


if __name__ == "__main__":
    sys.exit(main())
