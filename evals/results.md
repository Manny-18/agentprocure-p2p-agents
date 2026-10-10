| ID | Case | Expected | Actual | Controls | Values | Pass |
|---|---|---|---|---|---|---|
| E01 | S1 baseline: clean strategic buy | COMPLETED | COMPLETED | ok | ok | PASS |
| E02 | Invoice price +0.8% (inside 1% tolerance) | COMPLETED | COMPLETED | ok | ok | PASS |
| E03 | Invoice price +1.5% (outside tolerance) | COMPLETED_WITH_HOLD | COMPLETED_WITH_HOLD | ok | ok | PASS |
| E04 | Large supplier invoice without IRN | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E05 | IRN generated 35 days after invoice date | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E06 | Inter-state invoice billed as CGST+SGST | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E07 | Same invoice already booked (number formatted differently) | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E08 | Bank account on invoice differs from master | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E09 | CFO rejects at approval | REJECTED | REJECTED | ok | ok | PASS |
| E10 | Only two quotes for a Rs 19 lakh buy | ESCALATED | ESCALATED | ok | ok | PASS |
| E11 | Cost center budget nearly exhausted | ESCALATED | ESCALATED | ok | ok | PASS |
| E12 | S2 baseline: price variance + QC rejection | COMPLETED_WITH_HOLD | COMPLETED_WITH_HOLD | ok | ok | PASS |
| E13 | S2 with correct price and no rejection | COMPLETED | COMPLETED | ok | ok | PASS |
| E14 | Invoice arrives with no goods receipt | ON_HOLD | ON_HOLD | ok | ok | PASS |
| E15 | S3 baseline: split purchase + vendor red flags | ESCALATED | ESCALATED | ok | ok | PASS |
| E16 | S3 after vendor KYC is fixed: split purchase alone still blocks | ESCALATED | ESCALATED | ok | ok | PASS |
| E17 | S4 baseline: TDS threshold crossing + overdue MSME invoice | COMPLETED | COMPLETED | ok | ok | PASS |
| E18 | S4 supplier still below Rs 50 lakh for the year | COMPLETED | COMPLETED | ok | ok | PASS |
| E19 | S4 supplier without PAN on record (5% TDS rate) | COMPLETED | COMPLETED | ok | ok | PASS |
| E20 | S4 with no overdue MSME items | COMPLETED | COMPLETED | ok | ok | PASS |
| E21 | Early-payment discount worth more than cost of funds | COMPLETED | COMPLETED | ok | ok | PASS |
| E22 | Medium enterprise is outside the MSMED 45-day rule | COMPLETED_WITH_HOLD | COMPLETED_WITH_HOLD | ok | ok | PASS |

**22/22 cases passed (100%).**