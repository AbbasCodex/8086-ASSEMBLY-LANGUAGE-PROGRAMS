# Payments reconciliation

A seeded, integer-money reconciliation demo for platform transactions and bank
settlements. It writes deterministic CSV inputs, a ground-truth manifest for
testing only, a machine-readable JSON report, a human-readable report, and a
filterable report UI. The reconciler does not import, accept, or read the
ground-truth manifest.

## Run

From this directory, with Python 3.10+:

```sh
python demo.py
python -m pytest -q
python export_static.py
```

`python demo.py` regenerates the data and reports, prints the totals and
conservation equation, lists the planted row IDs, and prints planted-gap
precision/recall. The generated inputs are in `data/`; the static site is
`docs/index.html`.

To preview the dynamic local report UI:

```sh
python app.py --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000`. To publish the static page on GitHub Pages:

```sh
python demo.py && python export_static.py
```

Then configure the repository's Pages source to the deployment branch and
`/docs` folder. `docs/index.html` contains the report data, styles, and
JavaScript inline and makes no external requests.

## Assumptions list

The full numbered record is [ASSUMPTIONS.md](./ASSUMPTIONS.md). The working
assumptions are:

1. **A1:** January and February 2025 are separate transaction-month cohorts.
2. **A2:** Timestamps are UTC; cutoff is the last instant of each calendar month.
3. **A3:** Generated currency is USD; money is read as integer thousandths and summarized in cents.
4. **A4:** Gross capture amounts and fees are positive; refund net amounts are negative.
5. **A5:** `net_amount` already includes the fee.
6. **A6:** Normal synthetic settlement lag is one or two calendar days; the planted timing case crosses month-end.
7. **A7:** Match bank reference first; otherwise match customer, currency, dates, and cent-rounded net within one cent.
8. **A8:** The settlement window is zero through two calendar days after creation, including weekends and holidays.
9. **A9:** Only identical business-field rows sharing a transaction ID are duplicates; differing same-ID rows remain visible for review.
10. **A10:** Refund parent existence is checked across all platform months; partial refunds are allowed.
11. **A11:** Rounding is checked on matched row sums per batch, currency, and settlement month, not per transaction.
12. **A12:** Platform totals use creation-month cohort; bank totals include that cohort's entries settled by its cutoff.
13. **A13:** All impact signs mean platform minus bank; unexplained is variance less explained and rounding amounts.
14. **A14:** Ground truth is emitted only by the generator and used by demo/tests for evaluation.
15. **A15:** One-cent net differences can match, but the signed impact remains explicit.
16. **A16:** A separate clean dataset and ten seeded generated datasets test false positives and conservation.

The original task and improvement prompts are preserved verbatim under
[`submission/prompts/`](./submission/prompts/). Export the complete chat thread
from the chat client separately; this project does not fabricate a transcript
export.

## How detection order works

1. **Canonicalize exact duplicates per source.** Rows with the same `txn_id`
   and identical business fields are emitted as `DUPLICATE_PLATFORM` or
   `DUPLICATE_BANK`; the remaining canonical rows are processed. Same-ID rows
   with different data are retained and can require human review.
2. **Identify orphan refunds.** A refund with no platform capture referenced
   by `original_txn_id` is `ORPHAN_REFUND`; parent lookup spans the full input,
   including prior months.
3. **Match remaining rows.** Try bank reference first, then fuzzy matching.
   Both paths require customer, currency, compatible status, a zero-to-two-day
   calendar window, and a cent-rounded net difference no greater than one cent.
   A matched settlement in the following month is `TIMING_NEXT_MONTH`;
   other pairs are `MATCHED`.
4. **Classify residual rows.** A same-reference, in-window amount outside
   tolerance is `AMOUNT_MISMATCH` and is flagged for human review; otherwise
   residual source rows are `UNMATCHED_PLATFORM` or `UNMATCHED_BANK`.
5. **Check batch rounding last.** For matched pairs equal at individual cent
   precision, compare integer source-precision sums per batch/currency/month.
   Only a nonzero aggregate delta creates `ROUNDING_DIFFERENCE`.

Each classification includes its rule ID, plain-English reason, signed impact
in integer cents, confidence, and human-review flag. Summary arithmetic is
integer-cent arithmetic; source strings allow up to three decimal places so the
planted sub-cent rounding effect remains reproducible.
