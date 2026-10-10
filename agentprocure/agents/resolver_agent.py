"""Exception Resolver: split payable from disputed, request a credit note, draft the supplier email."""
from __future__ import annotations

from .. import config
from ..llm import GATEWAY
from ..rules.common import add_days, inr
from .base import StepRecorder
from .personas import PERSONAS

OWNER = {"PRICE_VARIANCE": "Buyer", "QTY_EXCEEDS_ACCEPTED": "Quality + Buyer", "QTY_EXCEEDS_PO": "Buyer",
         "FREIGHT_NOT_AGREED": "Buyer", "PROBABLE_DUPLICATE": "AP Lead", "DUPLICATE_INVOICE": "AP Lead",
         "BANK_CHANGE_UNVERIFIED": "Vendor Master team", "BANK_ON_INVOICE_DIFFERS": "Vendor Master team",
         "TAX_AMOUNT_MISMATCH": "Tax team", "TOTAL_MISMATCH": "AP Lead", "IRN_MISSING": "Tax team", "IRN_LATE": "Tax team"}


def resolver_agent(state: dict) -> dict:
    s, po, ap, tax = state["scenario"], state["po"], state["ap"], state["tax"]
    inv = s["invoice"]
    co, vendors = config.company(), config.vendors()
    v = vendors[inv["vendor_id"]]
    rec = StepRecorder("resolver")
    issues = [i for i in ap["findings"] + tax["issues"] if i["severity"] in ("BLOCK", "HOLD")]
    hard_stop = any(i["severity"] == "BLOCK" for i in issues)
    m = ap["match"]

    actions = []
    for i in issues:
        actions.append({"code": i["code"], "owner": OWNER.get(i["code"], "AP Lead"), "detail": i["detail"],
                        "sla": add_days(co["as_of"], 2 if i["severity"] == "BLOCK" else 3).isoformat()})
    rec.tool("route_exceptions", {"count": len(issues)}, actions, f"{len(actions)} action(s) assigned to owners")

    credit_note = None
    if not hard_stop and m["disputed_total"] > 0.5:
        credit_note = {"requested_from": v["name"], "against_invoice": inv["invoice_no"],
                       "taxable": m["disputed_taxable"], "tax": tax["itc_on_hold"], "total": m["disputed_total"],
                       "basis": "CGST Act s.34 credit note for rejected quantity and price above PO"}
        rec.tool("credit_note_request", {"invoice": inv["invoice_no"]}, credit_note,
                 f"Credit note for {inr(m['disputed_total'])} ({inr(m['disputed_taxable'])} + tax {inr(tax['itc_on_hold'])})")

    lines = []
    for i in ap["findings"]:
        if i["code"] == "PRICE_VARIANCE":
            lines.append(f"- Unit price: invoiced {inr(m['invoice_price'])} against the PO price of {inr(m['po_price'])}.")
        if i["code"] == "QTY_EXCEEDS_ACCEPTED":
            lines.append(f"- Quantity: {m['invoiced_qty']:,} invoiced, {m['accepted_qty']:,} accepted after inspection "
                         f"({(s.get('grn') or {}).get('remarks', '')}).")
    email = (f"Subject: {inv['invoice_no']} against {po['po_no']} - partial approval and credit note request\n\n"
             f"Dear {v['name']} team,\n\nWe have processed invoice {inv['invoice_no']} dated {inv['date']}. "
             f"We are releasing {inr(m['approved_total'])} for the accepted quantity at the PO price, as per terms.\n\n"
             "The balance is on hold for these reasons:\n" + "\n".join(lines) +
             f"\n\nPlease issue a GST credit note for {inr(m['disputed_total'])} (taxable {inr(m['disputed_taxable'])} plus tax) "
             "within 7 days, quoting the invoice number. Rejected parts are available for collection at our Chakan stores.\n\n"
             "Regards,\nAccounts Payable, Meridian Precision Components") if credit_note else None
    if email:
        rec.tool("draft_supplier_email", {"to": v["name"]}, email, "Supplier email drafted (partial approval + credit note request)")

    decision = ("HOLD ENTIRE INVOICE - hard-stop control failed" if hard_stop else
                f"Pay undisputed {inr(m['approved_total'])}; hold {inr(m['disputed_total'])} pending credit note")
    facts = {"approved_total": m["approved_total"], "disputed_total": m["disputed_total"], "actions": actions,
             "credit_note": credit_note, "hard_stop": hard_stop}
    fallback = (("Hard-stop control failed; nothing is paid until the owners clear: " + "; ".join(a["code"] for a in actions) + ".")
                if hard_stop else
                (f"Paying the undisputed {inr(m['approved_total'])} on time protects the supplier relationship and our terms; "
                 f"{inr(m['disputed_total'])} stays on hold until the supplier issues a credit note. "
                 + " ".join(f"{a['owner']} owns {a['code']} (due {a['sla']})." for a in actions)))
    rationale = GATEWAY.narrate(persona=PERSONAS["resolver"]["system"], task="Explain the resolution plan in 2-3 sentences.",
                                facts=facts, fallback=fallback)
    report = rec.report(decision=decision, findings=issues, rationale=rationale,
                        highlights=[f"Release {inr(m['approved_total'])}" if not hard_stop else "Release Rs 0",
                                    f"Hold {inr(m['disputed_total'])}" if not hard_stop else f"Hold {inr(m['billed_total'])}",
                                    f"{len(actions)} owner action(s)"],
                        extra={"email_draft": email})
    return {"resolution": {"hard_stop": hard_stop, "actions": actions, "credit_note": credit_note, "email_draft": email,
                           "release_amount": 0.0 if hard_stop else m["approved_total"]},
            "trace": [report], "status": "EXCEPTION_HOLD_ALL" if hard_stop else "EXCEPTION_PARTIAL_RELEASE"}
