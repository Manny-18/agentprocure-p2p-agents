"""Sourcing expertise: Kraljic portfolio matrix, weighted supplier scorecard, should-cost model
and negotiation levers. These are the tools the CrewAI sourcing crew calls."""
from __future__ import annotations

from .common import r2

HIGH_SPEND = 10_000_000  # Rs 1 crore annual spend = high profit impact for this company

WEIGHTS = {  # by Kraljic quadrant; must sum to 1
    "Strategic":    {"price": 0.25, "quality": 0.30, "delivery": 0.20, "risk": 0.20, "compliance": 0.05},
    "Leverage":     {"price": 0.40, "quality": 0.25, "delivery": 0.20, "risk": 0.10, "compliance": 0.05},
    "Bottleneck":   {"price": 0.15, "quality": 0.25, "delivery": 0.30, "risk": 0.25, "compliance": 0.05},
    "Non-critical": {"price": 0.35, "quality": 0.20, "delivery": 0.25, "risk": 0.10, "compliance": 0.10},
}

LEVERS = {
    "Strategic": [
        "Long-term agreement with index-linked raw-material pricing (share commodity risk transparently)",
        "Develop the runner-up as a qualified second source for 20-30% of volume",
        "Joint cost-reduction (VA/VE) targets and PPM improvement plan written into the contract",
    ],
    "Leverage": [
        "Use competitive tension: share the target price and invite a best-and-final offer",
        "Volume consolidation across plants for a tiered price",
        "Trade payment-term flexibility for price only where the annualised maths favours us",
    ],
    "Bottleneck": [
        "Secure supply first: buffer stock and capacity reservation",
        "Qualify alternate specifications or suppliers to reduce dependence",
    ],
    "Non-critical": [
        "Rate contract / catalogue buying to cut transaction cost",
        "Bundle with similar items; automate re-orders",
    ],
}


def supply_risk_score(qualified_suppliers: int, lead_time_days: float, criticality: str) -> int:
    score = 2 if qualified_suppliers <= 2 else (1 if qualified_suppliers <= 4 else 0)
    score += 2 if lead_time_days > 45 else (1 if lead_time_days >= 21 else 0)
    score += 1 if criticality == "high" else 0
    return score


def kraljic(*, annual_spend: float, qualified_suppliers: int, lead_time_days: float, criticality: str) -> dict:
    risk = supply_risk_score(qualified_suppliers, lead_time_days, criticality)
    high_impact = annual_spend >= HIGH_SPEND
    high_risk = risk >= 3
    quadrant = {(True, True): "Strategic", (True, False): "Leverage",
                (False, True): "Bottleneck", (False, False): "Non-critical"}[(high_impact, high_risk)]
    return {"quadrant": quadrant, "annual_spend": annual_spend, "profit_impact": "high" if high_impact else "low",
            "supply_risk_score": risk, "supply_risk": "high" if high_risk else "low",
            "weights": WEIGHTS[quadrant], "levers": LEVERS[quadrant]}


def landed_unit_cost(quote: dict, qty: float) -> float:
    return r2(quote["unit_price"] + (quote.get("freight") or 0) / qty)


def scorecard(*, quotes: list[dict], vendors: dict, qty: float, weights: dict,
              excluded: list[str] | None = None, infeasible: list[str] | None = None) -> dict:
    """Score each quote 0-100 on five criteria and rank by weighted total.
    price = lowest landed cost / own landed cost; quality = 100 - PPM/40; delivery = OTIF %;
    risk = (6 - financial risk rating) x 20; compliance = vendor compliance score."""
    excluded, infeasible = excluded or [], infeasible or []
    landed = {q["vendor_id"]: landed_unit_cost(q, qty) for q in quotes}
    best = min(landed.values())
    rows = []
    for q in quotes:
        v = vendors[q["vendor_id"]]
        p = v["performance"]
        parts = {
            "price": round(best / landed[q["vendor_id"]] * 100, 2),
            "quality": round(max(0.0, 100 - p["quality_ppm"] / 40), 2),
            "delivery": float(p["otif_pct"]),
            "risk": float((6 - p["financial_risk"]) * 20),
            "compliance": float(p["compliance_score"]),
        }
        total = round(sum(parts[k] * weights[k] for k in weights), 2)
        eligible = q["vendor_id"] not in excluded and q["vendor_id"] not in infeasible
        note = ("excluded: failed due diligence" if q["vendor_id"] in excluded else
                "excluded: lead time misses need-by date" if q["vendor_id"] in infeasible else "")
        rows.append({"vendor_id": q["vendor_id"], "vendor": v["name"], "unit_price": q["unit_price"],
                     "landed_unit_cost": landed[q["vendor_id"]], "lead_time_days": q["lead_time_days"],
                     "msme": v["msme"]["category"], "state_code": v["state_code"], "scores": parts,
                     "weighted_total": total, "eligible": eligible, "note": note})
    rows.sort(key=lambda r: (not r["eligible"], -r["weighted_total"]))
    winner = rows[0] if rows and rows[0]["eligible"] else None
    cheapest = min(rows, key=lambda r: r["landed_unit_cost"])
    runner_up = next((r for r in rows[1:] if r["eligible"]), None)
    return {"ranking": rows, "recommended": winner, "runner_up": runner_up, "cheapest": cheapest,
            "margin_vs_runner_up": round(winner["weighted_total"] - runner_up["weighted_total"], 2) if winner and runner_up else None,
            "weights": weights}


def should_cost(model: dict | None, quoted_price: float, qty: float, annual_qty: float) -> dict | None:
    """Bottom-up cost: material + conversion + secondary ops, plus overhead and margin."""
    if not model:
        return None
    material = model["material_kg"] * model["material_rate_per_kg"]
    base = material + model["conversion"] + model["secondary_ops"]
    target = r2(base * (1 + model["overhead_margin_pct"] / 100))
    gap = r2(quoted_price - target)
    gap_pct = round(gap / quoted_price * 100, 2)
    return {"material_cost": r2(material), "conversion": model["conversion"], "secondary_ops": model["secondary_ops"],
            "overhead_margin_pct": model["overhead_margin_pct"], "should_cost": target, "quoted": quoted_price,
            "gap_per_unit": gap, "gap_pct": gap_pct,
            "saving_this_order": r2(gap * qty) if gap_pct > 1.0 else 0.0,
            "saving_annualised": r2(gap * annual_qty) if gap_pct > 1.0 else 0.0,
            "verdict": "negotiate" if gap_pct > 1.0 else "price is fair (within 1% of should-cost)"}
