# Meridian Procurement Policy

Version 3.2, effective 1 April 2026. Fictional policy written for this academic project; it mirrors the rules the agents enforce in `agentprocure/data/company.json`.

## POL-1 Scope and principles

### POL-1.1 Scope
This policy applies to every purchase of goods and services by Meridian Precision Components Pvt. Ltd., at every plant and cost center, whatever the value or urgency.

### POL-1.2 No PO, no payment
A supplier invoice is paid only against an approved purchase order (PO) and a goods receipt (GRN). Purchases made without a PO are reported to the CFO and need retrospective approval one level above the normal approver.

## POL-2 Delegation of authority

### POL-2.1 Approval limits
A purchase order must be approved by the holder of the authority that matches its value excluding GST. Up to Rs 2 lakh: Department Head. Above Rs 2 lakh and up to Rs 10 lakh: Plant Head. Above Rs 10 lakh and up to Rs 1 crore: CFO. Above Rs 1 crore: Managing Director. Related requisitions that are aggregated under POL-4.2 are approved at the level of their combined value.

### POL-2.2 Sole-source approval
A sole-source or single-source purchase accepted under POL-4.3 needs approval one level above the normal approver for its value.

### POL-2.3 Segregation of duties
A requester cannot approve their own requisition. A buyer cannot approve a purchase order they negotiated. Accounts Payable cannot create or change vendor master data, and no one who can change vendor bank details can release payments.

## POL-3 Purchase requisitions

### POL-3.1 Content of a requisition
Every requisition states the item and specification, quantity and unit, need-by date, estimated value, cost center and category. Requests that miss any of these are returned to the requester before sourcing starts.

### POL-3.2 Budget check
A requisition is released for sourcing only if the cost center has enough remaining budget for the year (budget less consumed less committed). If pending requisitions on the same cost center would exceed the budget, the approver is warned. Requests over the remaining budget need a budget transfer approved by the CFO.

### POL-3.3 Urgent requests
Urgency does not waive any part of this policy. A genuine emergency (safety, statutory or line-stoppage) may be bought on a verbal approval from the Plant Head, but the requisition, quotes and approval must be completed within 3 working days. Pressure to approve fast is a known fraud indicator and is noted on the case.

## POL-4 Competitive sourcing

### POL-4.1 Number of quotations
Quotations are required according to the purchase value excluding GST: below Rs 50,000 one quote; up to Rs 5 lakh two quotes; up to Rs 25 lakh three quotes; above Rs 25 lakh at least three quotes through a formal RFQ or e-auction run by the Category Manager.

### POL-4.2 Splitting purchases is prohibited
A need must not be divided into smaller orders to stay below an approval or quotation threshold. Requisitions raised within 30 days by the same requester or cost center, for the same vendor or category, are aggregated; if the combined value falls in a stricter band under POL-2.1 or POL-4.1, the stricter rule applies and the case is referred to the Procurement Head and Internal Audit.

### POL-4.3 Sole-source justification
Buying from one supplier without competition is allowed only with a documented reason: a proprietary or OEM-specific part, intellectual property held by the supplier, a documented capability gap among other qualified suppliers, or an emergency under POL-3.3. Familiarity with the supplier, convenience, a past relationship or a previous phase of the same work are not acceptable reasons.

### POL-4.4 Supplier evaluation on total value
Suppliers are selected on a weighted scorecard, not on price alone. The Category Manager places each category in the Kraljic matrix and the weights follow the quadrant: strategic items weight quality and risk most; leverage items weight price most; bottleneck items weight delivery and supply assurance; non-critical items weight price, delivery and ease of buying. Landed cost (price plus freight) is used for price.

### POL-4.5 Lead time
A quote whose lead time cannot meet the need-by date, after allowing two days to issue the PO, is not eligible for award.

## POL-5 Vendor master and know-your-supplier checks

### POL-5.1 Onboarding and KYC
A vendor is added to the approved list only after the GSTIN is checked for format, state code, check digit and active status on the GST portal; the PAN inside the GSTIN matches the PAN on the vendor's PAN card; MSME status is recorded from the Udyam certificate; and bank details are confirmed by a cancelled cheque or bank letter. A vendor failing any check is blocked until corrected.

### POL-5.2 Bank detail changes
A request to change a vendor's bank account is accepted only on the vendor's letterhead and only after a call-back to a phone number already in the vendor master, never a number given in the request. Requests by e-mail alone are rejected. For 30 days after a change, every payment to the new account needs release by the Treasury Head after the call-back is recorded. An unverified change is a hard stop for all payments to that vendor.

### POL-5.3 Vendor without PAN
If a vendor has not furnished a PAN, payment is not stopped, but TDS on purchase of goods is deducted at the higher rate of 5% and the vendor is asked to furnish the PAN before the next payment.

## POL-6 Purchase orders

### POL-6.1 Purchase order terms
Every PO states price, quantity, delivery date, payment terms and the buyer's GSTIN. For a micro or small enterprise supplier it states that payment will be made within the agreed term and never more than 45 days from acceptance. For a supplier above the e-invoicing threshold it states that invoices without an IRN will be rejected. Invoices must quote the PO number and bill only accepted quantities.

## POL-7 Invoice processing

### POL-7.1 Three-way match and tolerances
Each invoice is matched to its PO and GRN. The invoice unit price may exceed the PO price by at most 1%; above that the difference is disputed. Only the quantity accepted at goods receipt is paid. Freight is paid only if it is on the PO. An invoice from a vendor other than the PO vendor, or with no goods receipt, is held.

### POL-7.2 Partial payment of undisputed amounts
When only part of an invoice is disputed, the undisputed amount is paid on its due date and only the disputed part is held. The supplier is asked for a GST credit note for the disputed amount, and the buyer and quality team own its resolution.

### POL-7.3 Duplicate invoices
Before payment every invoice is checked against invoices already booked for the same vendor. An invoice whose number matches an existing one after removing spaces, punctuation and leading zeros is a duplicate and is blocked. The same amount from the same vendor within 7 days is held for review as a probable duplicate.

### POL-7.4 Input tax credit
GST input tax credit is claimed only on the accepted value, only for invoices reflected in GSTR-2B, and only while the supplier is paid within 180 days of the invoice date. Tax on a disputed portion is claimed only after the credit note is settled.

## POL-8 Payments

### POL-8.1 Payment runs and priority
Payments are released in a weekly payment run. Priority order: overdue micro and small enterprise dues with statutory interest; micro and small enterprise dues falling due within 7 days; early-payment discounts worth taking under POL-8.2; all other invoices on their due date.

### POL-8.2 Early-payment discounts
An early-payment discount is taken only if its annualised return is higher than the company's cost of funds, currently 9.25% a year. The annualised return is d / (1 - d) x 365 / (net days - discount days), where d is the discount rate. Otherwise the invoice is paid on its due date.

### POL-8.3 Paying micro and small enterprises on time
Micro and small enterprise suppliers are paid within the agreed term and never later than 45 days from acceptance of the goods, or within 15 days if there is no written agreement. Any such invoice still awaiting approval 30 days after acceptance is escalated to the CFO. The company files the half-yearly MSME Form I return for dues outstanding beyond 45 days.

## POL-9 Records and audit

### POL-9.1 Audit trail
Every requisition, approval, purchase order, invoice decision and payment, including each AI agent's tools, findings, decision and reasoning, is kept for 8 years and is available to Internal Audit.
