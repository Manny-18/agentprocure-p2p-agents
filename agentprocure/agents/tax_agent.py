"""GST & TDS Specialist: is the invoice a valid tax document, can we take ITC, how much TDS?"""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import inr
from ..rules.gst import check_invoice_tax, einvoice_check, itc_readiness
from ..rules.tds import tds_on_goods
from .base import StepRecorder
from .personas import PERSONAS


def tax_agent(state: dict) -> dict:
    s, ap = state["scenario"], state["ap"]
    inv, grn = s["invoice"], s.get("grn")
    co, vendors, rates = config.company(), config.vendors(), config.hsn_rates()
    v = vendors[inv["vendor_id"]]
    rec = StepRecorder("tax")

    gst = check_invoice_tax(inv, v, co, rates)
    exp = gst["expected"]
    rec.tool("gst_invoice_check", {"invoice": inv["invoice_no"], "supplier_state": v["state_code"], "place_of_supply": inv["place_of_supply"]},
             gst, f"{exp['tax_type']} @ {exp['rate_pct']}% on {inr(exp['taxable'])} = {inr(exp['tax_total'])}; "
                  f"GSTIN checksum {'OK' if gst['gstin']['checksum_ok'] else 'FAIL'}; "
                  + ("no tax errors" if not gst["issues"] else f"{len(gst['issues'])} issue(s)"))
    ein = einvoice_check(inv, v)
    rec.tool("einvoice_check", {"supplier_aato_cr": v["aato_cr"]}, ein,
             (f"E-invoice required (AATO Rs {v['aato_cr']} cr); IRN present, reported {ein['irn_lag_days']} day(s) after invoice"
              if ein["required"] and ein["irn_present"] else
              "E-invoice not required (AATO up to Rs 5 cr)" if not ein["required"] else "IRN missing"))
    issues = gst["issues"] + ein["issues"]
    itc = itc_readiness(inv, grn, issues)
    approved_taxable = ap["match"]["approved_taxable"]
    itc_amount = round(ap["match"]["approved_tax"], 2) if itc["eligible_now"] else 0.0
    rec.tool("itc_readiness", {"in_gstr2b": inv.get("in_gstr2b")}, itc,
             f"ITC claimable now: {inr(itc_amount)}" + ("" if itc["eligible_now"] else " (conditions not met)"))
    tds = tds_on_goods(buyer_prev_turnover_cr=co["prev_year_turnover_cr"], seller_pan=v["pan"],
                       cumulative_before=v["purchases_ty_to_date"], this_taxable=approved_taxable)
    rec.tool("tds_on_goods", {"cumulative_before": v["purchases_ty_to_date"], "this_taxable": approved_taxable}, tds,
             f"TDS {inr(tds['tds_amount'])} at {tds['rate_pct']}% on {inr(tds['base'])}: {tds['reason']}")

    if tds["applicable"] and not v.get("pan"):
        issues = issues + [{"code": "TDS_HIGHER_RATE_NO_PAN", "severity": "WARN",
                            "detail": f"Seller PAN not furnished: TDS at {tds['rate_pct']}% = {inr(tds['tds_amount'])} instead of 0.1%"}]
    disputed_tax = round(ap["match"]["billed_total"] - ap["match"]["billed_taxable"] - ap["match"]["approved_tax"], 2)
    facts = {"tax_type": exp["tax_type"], "rate_pct": exp["rate_pct"], "tax_total": exp["tax_total"], "issues": issues,
             "einvoice_required": ein["required"], "irn_lag_days": ein["irn_lag_days"], "itc_claimable": itc_amount,
             "itc_on_disputed_portion": disputed_tax, "tds": tds, "itc_reversal_deadline_days": 180}
    fallback = (f"Tax document check: {exp['tax_type']} at {exp['rate_pct']}% is correct for a supply from state {v['state_code']} to "
                f"place of supply {inv['place_of_supply']}; billed tax reconciles. "
                + ("E-invoice IRN verified. " if ein["required"] and ein["irn_present"] else ("E-invoice not mandatory for this supplier. " if not ein["required"] else ""))
                + f"Claim ITC of {inr(itc_amount)} on the accepted value"
                + (f"; do not claim the {inr(disputed_tax)} of tax on the disputed portion until the credit note arrives" if disputed_tax > 0.5 else "")
                + f". TDS: {tds['reason'][0].lower() + tds['reason'][1:]}"
                + (f" - deduct {inr(tds['tds_amount'])} under {tds['provision']}." if tds["applicable"] else ".")
                + " Pay the supplier within 180 days of invoice date to keep the ITC.")
    if issues:
        fallback = "Tax issues: " + " ".join(f"{i['detail']}." for i in issues) + " " + fallback
    rationale = GATEWAY.narrate(persona=PERSONAS["tax"]["system"],
                                task="Give the GST and TDS conclusion with the provision and money impact.", facts=facts, fallback=fallback)
    blocked = any(i["severity"] == "BLOCK" for i in issues)
    report = rec.report(decision=("Tax BLOCK - invoice not valid for ITC/payment" if blocked else
                                  f"Valid tax invoice; ITC {inr(itc_amount)}; TDS {inr(tds['tds_amount'])}"),
                        findings=issues, rationale=rationale,
                        highlights=[f"{exp['tax_type']} {exp['rate_pct']}%", f"ITC {inr(itc_amount)}", f"TDS {inr(tds['tds_amount'])}"])
    return {"tax": {"gst": gst, "einvoice": ein, "itc": itc, "itc_amount": itc_amount, "itc_on_hold": max(disputed_tax, 0.0),
                    "tds": tds, "issues": issues, "blocked": blocked},
            "trace": [report], "status": "TAX_BLOCKED" if blocked else "TAX_CLEARED"}
