/* AgentProcure rules engine, browser port of agentprocure/rules/*.py (used by the What-if lab).
   Kept as plain functions so the same file can be unit-checked in Node. */
const P2P = (() => {
  const CH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const STATES = {"01":"Jammu and Kashmir","02":"Himachal Pradesh","03":"Punjab","04":"Chandigarh","05":"Uttarakhand","06":"Haryana","07":"Delhi","08":"Rajasthan","09":"Uttar Pradesh","10":"Bihar","11":"Sikkim","12":"Arunachal Pradesh","13":"Nagaland","14":"Manipur","15":"Mizoram","16":"Tripura","17":"Meghalaya","18":"Assam","19":"West Bengal","20":"Jharkhand","21":"Odisha","22":"Chhattisgarh","23":"Madhya Pradesh","24":"Gujarat","26":"Dadra and Nagar Haveli and Daman and Diu","27":"Maharashtra","29":"Karnataka","30":"Goa","31":"Lakshadweep","32":"Kerala","33":"Tamil Nadu","34":"Puducherry","35":"Andaman and Nicobar Islands","36":"Telangana","37":"Andhra Pradesh","38":"Ladakh","97":"Other Territory"};
  const r2 = x => Math.round((x + Number.EPSILON) * 100) / 100;
  const day = s => { const [y, m, d] = s.split("-").map(Number); return Date.UTC(y, m - 1, d); };
  const iso = t => new Date(t).toISOString().slice(0, 10);
  const addDays = (s, n) => iso(day(s) + n * 86400000);
  const between = (a, b) => Math.round((day(b) - day(a)) / 86400000);

  function gstinChecksum(first14) {
    let factor = 2, total = 0;
    for (const ch of first14.split("").reverse()) {
      const a = factor * CH.indexOf(ch);
      factor = factor === 2 ? 1 : 2;
      total += Math.floor(a / 36) + (a % 36);
    }
    return CH[(36 - (total % 36)) % 36];
  }

  function validateGstin(g, pan) {
    g = (g || "").trim().toUpperCase();
    const out = { gstin: g, issues: [], state: null, pan: null, expected: null };
    if (!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(g)) {
      out.issues.push(["GSTIN_FORMAT_INVALID", "Not a 15-character GSTIN (2-digit state + PAN + entity no. + Z + check digit)"]);
      return out;
    }
    out.state = STATES[g.slice(0, 2)] || null;
    out.pan = g.slice(2, 12);
    out.expected = gstinChecksum(g.slice(0, 14));
    if (!out.state) out.issues.push(["GSTIN_STATE_INVALID", `State code ${g.slice(0, 2)} does not exist`]);
    if (out.expected !== g[14]) out.issues.push(["GSTIN_CHECKSUM_INVALID", `Check digit is '${g[14]}', expected '${out.expected}'`]);
    if (pan && pan.toUpperCase() !== out.pan) out.issues.push(["PAN_MISMATCH", `PAN in GSTIN ${out.pan} differs from ${pan.toUpperCase()}`]);
    return out;
  }

  function taxSplit(taxable, rate, interState) {
    const igst = interState ? r2(taxable * rate / 100) : 0;
    const half = interState ? 0 : r2(taxable * rate / 200);
    return { igst, cgst: half, sgst: half, tax: r2(igst + 2 * half), total: r2(taxable + igst + 2 * half) };
  }

  function threeWayMatch({ poPrice, poQty, acceptedQty, invQty, invPrice, rate, tolPct = 1 }) {
    const ex = [];
    const varPct = (invPrice - poPrice) / poPrice * 100;
    if (varPct > tolPct) ex.push(["PRICE_VARIANCE", `+${varPct.toFixed(2)}% over PO (tolerance ${tolPct}%)`, r2((invPrice - poPrice) * Math.min(invQty, acceptedQty))]);
    if (invQty > acceptedQty) ex.push(["QTY_EXCEEDS_ACCEPTED", `${invQty.toLocaleString("en-IN")} invoiced vs ${acceptedQty.toLocaleString("en-IN")} accepted`, r2((invQty - acceptedQty) * invPrice)]);
    if (invQty > poQty) ex.push(["QTY_EXCEEDS_PO", `${invQty.toLocaleString("en-IN")} invoiced vs PO ${poQty.toLocaleString("en-IN")}`, 0]);
    const payQty = Math.min(invQty, acceptedQty);
    const payPrice = varPct > tolPct ? Math.min(invPrice, poPrice) : invPrice;
    const approvedTaxable = r2(payQty * payPrice);
    const billedTaxable = r2(invQty * invPrice);
    const approvedTotal = r2(approvedTaxable * (1 + rate / 100));
    const billedTotal = r2(billedTaxable * (1 + rate / 100));
    return { status: ex.length ? "EXCEPTION" : "MATCHED", exceptions: ex, varPct: r2(varPct), approvedTaxable, billedTaxable,
             approvedTotal, billedTotal, disputedTotal: r2(billedTotal - approvedTotal), disputedTax: r2((billedTotal - billedTaxable) - (approvedTotal - approvedTaxable)) };
  }

  function tdsOnGoods({ buyerTurnoverCr, hasPan, cumBefore, thisTaxable }) {
    const T = 5000000;
    if (buyerTurnoverCr <= 10) return { tds: 0, base: 0, rate: 0, note: "Buyer turnover not above Rs 10 crore: provision does not apply" };
    const base = Math.max(0, cumBefore + thisTaxable - T) - Math.max(0, cumBefore - T);
    const rate = hasPan ? 0.1 : 5;
    if (base <= 0) return { tds: 0, base: 0, rate, note: `Still below Rs 50 lakh this tax year (headroom ${inr(T - cumBefore - thisTaxable)})` };
    return { tds: Math.round(base * rate / 100), base, rate,
             note: cumBefore >= T ? "Threshold crossed earlier: TDS on the full value" : "Crosses Rs 50 lakh now: TDS only on the excess" };
  }

  function msmeDue({ acceptDate, category, written, agreedDays }) {
    if (!["micro", "small"].includes(category)) return { covered: false, due: null, days: null };
    const days = written ? Math.min(agreedDays, 45) : 15;
    return { covered: true, days, due: addDays(acceptDate, days) };
  }

  function msmeInterest({ principal, due, asOf, bankRate }) {
    const annual = 3 * bankRate / 100;
    const late = Math.max(0, between(due, asOf));
    const months = late / (365 / 12);
    return { annualPct: r2(annual * 100), late, interest: late ? r2(principal * (Math.pow(1 + annual / 12, months) - 1)) : 0 };
  }

  function discountApr(pct, ddays, net) {
    const d = pct / 100;
    return r2(d / (1 - d) * 365 / (net - ddays) * 100);
  }

  const DOA = [[200000, "Department Head"], [1000000, "Plant Head"], [10000000, "CFO"], [Infinity, "Managing Director"]];
  const QUOTES = [[50000, 1, false], [500000, 2, false], [2500000, 3, false], [Infinity, 3, true]];
  const approverFor = v => DOA.find(([m]) => v <= m)[1];
  const quoteRule = v => { const q = QUOTES.find(([m]) => v <= m); return { min: q[1], rfq: q[2] }; };

  function inr(x, dec) {
    if (x === null || x === undefined || Number.isNaN(x)) return "-";
    const neg = x < 0; x = Math.abs(x);
    if (dec === undefined) dec = Number.isInteger(r2(x)) ? 0 : 2;
    let [w, f] = x.toFixed(dec).split(".");
    if (w.length > 3) {
      let head = w.slice(0, -3); const tail = w.slice(-3); const g = [];
      while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) g.unshift(head);
      w = g.concat(tail).join(",");
    }
    return (neg ? "-" : "") + "₹" + w + (f ? "." + f : "");
  }

  return { gstinChecksum, validateGstin, taxSplit, threeWayMatch, tdsOnGoods, msmeDue, msmeInterest, discountApr,
           approverFor, quoteRule, inr, addDays, between, STATES };
})();
if (typeof module !== "undefined") module.exports = P2P;
