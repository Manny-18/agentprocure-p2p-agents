"""Buyer: issue a compliant PO with commercial and statutory terms."""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import add_days, inr
from ..rules.gst import EINVOICE_AATO_CR, compute_tax
from ..rules.msme import COVERED
from ..rules.tds import tds_on_goods
from .base import StepRecorder
from .personas import PERSONAS


def po_agent(state: dict) -> dict:
    s, pr, src = state["scenario"], state["requisition"], state["sourcing"]
    co, vendors, rates = config.company(), config.vendors(), config.hsn_rates()
    q = src["recommended_quote"]
    v = vendors[q["vendor_id"]]
    rec = StepRecorder("buyer")
    qty = pr["item"]["qty"]
    taxable = round(q["unit_price"] * qty + (q.get("freight") or 0), 2)
    rate = rates.get(pr["hsn"], {}).get("rate", 18)
    tax = rec.tool("gst_estimate", {"taxable": taxable, "rate": rate}, compute_tax(taxable, rate, v["state_code"], co["state_code"]), "")
    rec.tools[-1]["summary"] = f"{tax['tax_type']} @ {rate}% = {inr(tax['tax_total'])}; PO total {inr(tax['invoice_total'])}"
    tds_preview = tds_on_goods(buyer_prev_turnover_cr=co["prev_year_turnover_cr"], seller_pan=v["pan"],
                               cumulative_before=v["purchases_ty_to_date"], this_taxable=taxable)
    rec.tool("tds_preview", {"vendor": q["vendor_id"]}, tds_preview, tds_preview["reason"])

    terms = [f"Price {inr(q['unit_price'])}/{pr['item']['uom']}, firm for this order",
             f"Payment: {v['terms']['payment_days']} days from invoice"]
    if v["msme"]["category"] in COVERED:
        terms.append(f"MSMED Act clause: supplier is a {v['msme']['category']} enterprise ({v['msme']['udyam']}); "
                     f"payment within {min(v['terms']['payment_days'], 45)} days of acceptance")
    if (v.get("aato_cr") or 0) > EINVOICE_AATO_CR:
        terms.append("Supplier must issue an e-invoice with IRN (AATO above Rs 5 crore); invoices without IRN will be rejected")
    terms.append("Quote PO number on invoice; bill only accepted quantity; GSTIN of buyer " + co["gstin"])
    if src["negotiation"].get("target_unit_price") and src["negotiation"]["target_unit_price"] < q["unit_price"]:
        terms.append(f"Commercial note: negotiate towards {inr(src['negotiation']['target_unit_price'])}/unit on the next release")

    po = {"po_no": "PO-" + pr["pr_no"].split("-", 1)[1], "date": s.get("po_date"), "vendor_id": q["vendor_id"], "vendor": v["name"],
          "item": pr["item"]["description"], "hsn": pr["hsn"], "qty": qty, "uom": pr["item"]["uom"], "unit_price": q["unit_price"],
          "freight": q.get("freight") or 0, "taxable": taxable, "tax": tax, "delivery_by": add_days(s.get("po_date") or pr["date"], q["lead_time_days"]).isoformat(),
          "terms": terms, "tds_preview": tds_preview, "approved_by": state["approval"]["approved_by"]}
    facts = {k: po[k] for k in ("po_no", "vendor", "qty", "unit_price", "taxable", "delivery_by")} | {"terms": terms, "tax_total": tax["tax_total"]}
    fallback = (f"{po['po_no']} issued to {v['name']} for {qty:,} {pr['item']['uom']} at {inr(q['unit_price'])} "
                f"({inr(taxable)} + {tax['tax_type']} {inr(tax['tax_total'])}). Delivery by {po['delivery_by']}. "
                "Key terms: " + "; ".join(terms[1:4]) + ".")
    rationale = GATEWAY.narrate(persona=PERSONAS["buyer"]["system"], task="Confirm the PO and its key terms in 2-3 sentences.",
                                facts=facts, fallback=fallback)
    report = rec.report(decision=f"{po['po_no']} issued ({inr(tax['invoice_total'])} incl. GST)", rationale=rationale,
                        highlights=[f"{tax['tax_type']} {inr(tax['tax_total'])}", f"Delivery by {po['delivery_by']}",
                                    "MSME clause added" if v["msme"]["category"] in COVERED else "Non-MSE supplier"])
    return {"po": po, "trace": [report], "status": "PO_ISSUED"}
