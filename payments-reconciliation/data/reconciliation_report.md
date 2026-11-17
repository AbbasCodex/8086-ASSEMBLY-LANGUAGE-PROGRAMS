# Reconciliation report

Reporting cohorts: 2025-01, 2025-02 (USD, UTC month-end cutoffs).

| Summary | Amount |
|---|---:|
| Platform total | 237556.89 USD |
| Bank total (settled by each cohort cutoff) | 237357.78 USD |
| Platform minus bank variance | 199.11 USD |
| Explained transaction deltas | 199.07 USD |
| Batch rounding residual | 0.04 USD |
| Unexplained residual | 0.00 USD |

Conservation check: `platform_total - bank_total - explained_delta - rounding_residual = unexplained_delta`.
**Conservation holds (< $0.01 unexplained): True**

## Classification breakdown

| Category | Findings | Example txn ID / batch |
|---|---:|---|
| MATCHED | 1999 | TX000001, TX000002, TX000003 |
| TIMING_NEXT_MONTH | 1 | TX001001 |
| AMOUNT_MISMATCH | 0 | — |
| DUPLICATE_PLATFORM | 1 | TX000501 |
| DUPLICATE_BANK | 1 | TX000701 |
| ORPHAN_REFUND | 1 | RF002001 |
| UNMATCHED_PLATFORM | 0 | — |
| UNMATCHED_BANK | 1 | BANK-ONLY-001 |
| ROUNDING_DIFFERENCE | 1 | BATCH-ROUNDING-20250111-USD |

Every finding records its category, transaction IDs, signed cent impact, rule, plain-English reason, confidence, and human-review flag.
