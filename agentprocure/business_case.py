"""Business case for Meridian Precision Components (fictional): value, cost, payback, NPV.

All inputs are explicit assumptions so a reviewer can challenge and change them.
Benchmarks used for the improvement ranges: Ardent Partners, "AP Metrics That Matter in 2026"
(average vs best-in-class: cost per invoice $9.90 vs $2.67, exception rate 19.9% vs 11.8%) and
APQC Open Standards Benchmarking (invoice cycle time 10.9 days average vs 3.1 days top performers).

  python -m agentprocure.business_case
"""
from __future__ import annotations

import json

BASE = {
    "annual_revenue_cr": 420,
    "procurement_spend_cr": 260,          # ~62% of revenue for an auto-components maker
    "direct_material_spend_cr": 170,
    "mse_share_of_spend": 0.30,
    "invoices_per_year": 36000,
    "pos_per_year": 9000,
    "p2p_ops_cost_lakh": 110,             # AP + PO desk + approvers' transactional time, fully loaded
    "exception_rate_now": 0.199,          # Ardent Partners 2026 average
    "exception_rate_target": 0.118,       # Ardent Partners 2026 best-in-class
    "minutes_per_exception": 50,
    "cost_per_hour": 650,                 # Rs, loaded AP analyst cost
    "should_cost_coverage": 0.40,         # share of direct spend where a should-cost model exists
    "negotiated_gap_captured_pct": 0.8,   # % price reduction realised on covered spend
    "overbilling_caught_pct": 0.04,       # % of spend: price/qty overbilling and duplicates stopped
    "late_mse_share": 0.06,               # share of MSE spend paid late today
    "avg_days_late": 18,
    "bank_rate_pct": 5.75,
    "ops_effort_reduction": 0.40,         # Year-1 reduction in transactional effort (best-in-class cost gap is ~73%)
    "one_time_cost_lakh": 38,             # ERP integration, data clean-up, change management, testing
    "run_cost_lakh": 24,                  # 1 FTE product owner/support, hosting, LLM API, monitoring
    "discount_rate": 0.12,
}

SCENARIOS = {"Conservative": 0.6, "Base": 1.0, "Optimistic": 1.4}


def value_drivers(a: dict, scale: float = 1.0) -> dict:
    lakh = 1e5
    cr = 1e7
    ops = a["p2p_ops_cost_lakh"] * a["ops_effort_reduction"] * scale
    exceptions_avoided = a["invoices_per_year"] * (a["exception_rate_now"] - a["exception_rate_target"]) * scale
    exception_cost = exceptions_avoided * a["minutes_per_exception"] / 60 * a["cost_per_hour"] / lakh
    negotiation = a["direct_material_spend_cr"] * cr * a["should_cost_coverage"] * a["negotiated_gap_captured_pct"] / 100 * scale / lakh
    leakage = a["procurement_spend_cr"] * cr * a["overbilling_caught_pct"] / 100 * scale / lakh
    mse_late = a["procurement_spend_cr"] * cr * a["mse_share_of_spend"] * a["late_mse_share"]
    interest = mse_late * (3 * a["bank_rate_pct"] / 100) * a["avg_days_late"] / 365 * min(scale, 1.0) / lakh
    return {
        "P2P operations effort (AP + PO desk)": round(ops, 1),
        "Negotiation to should-cost (direct material)": round(negotiation, 1),
        "Overbilling / duplicate payments stopped": round(leakage, 1),
        "MSMED Act interest avoided": round(interest, 1),
    }


def evaluate(a: dict = BASE) -> dict:
    out = {}
    for name, scale in SCENARIOS.items():
        drivers = value_drivers(a, scale)
        gross = sum(drivers.values())
        net = gross - a["run_cost_lakh"]
        npv = -a["one_time_cost_lakh"] + sum(net / (1 + a["discount_rate"]) ** y for y in (1, 2, 3))
        out[name] = {"drivers": drivers, "gross_benefit_lakh": round(gross, 1), "run_cost_lakh": a["run_cost_lakh"],
                     "net_annual_benefit_lakh": round(net, 1), "one_time_cost_lakh": a["one_time_cost_lakh"],
                     "payback_months": round(a["one_time_cost_lakh"] / net * 12, 1) if net > 0 else None,
                     "npv_3yr_lakh": round(npv, 1), "roi_3yr_pct": round((3 * net - a["one_time_cost_lakh"]) / (a["one_time_cost_lakh"] + 3 * a["run_cost_lakh"]) * 100)}
    mse_late = a["procurement_spend_cr"] * 1e7 * a["mse_share_of_spend"] * a["late_mse_share"]
    exc = a["invoices_per_year"] * (a["exception_rate_now"] - a["exception_rate_target"])
    out["operational_kpis"] = {
        "exceptions_avoided_per_year": round(exc),
        "exception_hours_released": round(exc * a["minutes_per_exception"] / 60),
        "note": "Exception effort is part of P2P operations cost, so it is not counted again as a separate benefit.",
    }
    out["risk_exposure_not_in_roi"] = {
        "mse_spend_paid_late_cr": round(mse_late / 1e7, 2),
        "note": "If late MSE dues are still unpaid at 31 March, that expense is disallowed for the year under Income-tax Act 2025 "
                "s.37(2)(g): a cash-tax timing hit, plus reputational and supply risk. Not counted as ROI.",
    }
    return out


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
