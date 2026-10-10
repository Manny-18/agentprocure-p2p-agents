"""TDS on purchase of goods under the Income-tax Act, 2025.

From 1 Apr 2026 the old s.194Q (Income-tax Act, 1961) sits in s.393(1) of the Income-tax Act,
2025 (Table, Sl. 8(ii)). Substance is unchanged:
  * buyer: turnover above Rs 10 crore in the preceding tax year
  * deduct 0.1% on purchases from a resident seller to the extent they exceed Rs 50 lakh in the tax year
  * 5% if the seller has not furnished PAN
  * not applicable where another TDS/TCS provision already applies to the transaction
  * base excludes GST when tax is deducted at the time of credit and GST is shown separately
    (CBDT Circular 13/2021 position, carried forward in practice)
"""
from __future__ import annotations

from .common import r0

GOODS_THRESHOLD = 5_000_000          # Rs 50 lakh per seller per tax year
BUYER_TURNOVER_LIMIT_CR = 10         # buyer's turnover in the preceding tax year
RATE_WITH_PAN = 0.001                # 0.1%
RATE_NO_PAN = 0.05                   # 5%
PROVISION = "Income-tax Act 2025, s.393(1) Table Sl. 8(ii) (formerly s.194Q)"


def tds_on_goods(*, buyer_prev_turnover_cr: float, seller_pan: str | None, cumulative_before: float,
                 this_taxable: float, other_provision_applies: bool = False) -> dict:
    out = {"provision": PROVISION, "threshold": GOODS_THRESHOLD, "cumulative_before": cumulative_before,
           "cumulative_after": cumulative_before + this_taxable, "this_taxable": this_taxable,
           "applicable": False, "base": 0.0, "rate_pct": 0.0, "tds_amount": 0, "reason": ""}
    if buyer_prev_turnover_cr <= BUYER_TURNOVER_LIMIT_CR:
        out["reason"] = "Buyer turnover not above Rs 10 crore in preceding year; provision not applicable"
        return out
    if other_provision_applies:
        out["reason"] = "Another TDS/TCS provision applies to this transaction; goods-purchase TDS excluded"
        return out
    excess_after = max(0.0, cumulative_before + this_taxable - GOODS_THRESHOLD)
    excess_before = max(0.0, cumulative_before - GOODS_THRESHOLD)
    base = excess_after - excess_before
    rate = RATE_WITH_PAN if seller_pan else RATE_NO_PAN
    out.update(base=base, rate_pct=rate * 100)
    if base <= 0:
        headroom = GOODS_THRESHOLD - out["cumulative_after"]
        out["reason"] = f"Cumulative purchases still below Rs 50 lakh (headroom Rs {headroom:,.0f}); no TDS yet"
        return out
    out.update(applicable=True, tds_amount=r0(base * rate))
    if excess_before == 0:
        out["reason"] = "This invoice crosses the Rs 50 lakh threshold; TDS only on the amount above it"
    else:
        out["reason"] = "Threshold already crossed earlier this tax year; TDS on the full taxable value"
    return out
