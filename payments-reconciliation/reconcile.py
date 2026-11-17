"""Integer-only deterministic transaction matching and variance reporting."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

TOLERANCE_CENTS = 1
BUCKETS = (
    "MATCHED",
    "TIMING_NEXT_MONTH",
    "AMOUNT_MISMATCH",
    "DUPLICATE_PLATFORM",
    "DUPLICATE_BANK",
    "ORPHAN_REFUND",
    "UNMATCHED_PLATFORM",
    "UNMATCHED_BANK",
    "ROUNDING_DIFFERENCE",
)


def parse_mills(value: str) -> int:
    """Parse a decimal money string into signed integer thousandths."""
    text = value.strip()
    if not text:
        return 0
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    whole, separator, fraction = text.partition(".")
    if len(fraction) > 3 or (separator and not fraction.isdigit()):
        raise ValueError(f"Money value supports at most three decimal places: {value!r}")
    if not whole.isdigit():
        raise ValueError(f"Invalid money value: {value!r}")
    return sign * (int(whole) * 1000 + int(fraction.ljust(3, "0") or "0"))


def mills_to_cents(mills: int) -> int:
    """Round integer thousandths to cents using half-away-from-zero."""
    sign = -1 if mills < 0 else 1
    absolute = abs(mills)
    cents, remainder = divmod(absolute, 10)
    if remainder >= 5:
        cents += 1
    return sign * cents


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}{dollars}.{remainder:02d}"


def format_mills(mills: int) -> str:
    sign = "-" if mills < 0 else ""
    dollars, remainder = divmod(abs(mills), 1000)
    return f"{sign}{dollars}.{remainder:03d}"


def _month(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%Y-%m")


def _day(value: str) -> date:
    return datetime.fromisoformat(value).date()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _signature(row: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, value) for key, value in row.items() if key != "row_id"))


def _record(
    category: str,
    platform_row: dict[str, str] | None = None,
    bank_row: dict[str, str] | None = None,
    *,
    impact_cents: int = 0,
    rule: str,
    reason: str,
    confidence: str = "high",
    needs_review: bool = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    platform_mills = parse_mills(platform_row["net_amount"]) if platform_row else 0
    bank_mills = parse_mills(bank_row["net_amount"]) if bank_row else 0
    txn_ids = sorted(
        {
            row["txn_id"]
            for row in (platform_row, bank_row)
            if row is not None
        }
    )
    result: dict[str, object] = {
        "category": category,
        "bucket": category,
        "txn_ids": txn_ids,
        "txn_id": txn_ids[0] if len(txn_ids) == 1 else None,
        "platform_row_id": platform_row["row_id"] if platform_row else None,
        "bank_row_id": bank_row["row_id"] if bank_row else None,
        "batch_id": (platform_row or bank_row or {}).get("settlement_batch_id", ""),
        "currency": (platform_row or bank_row or {}).get("currency", ""),
        "platform_net_mills": platform_mills,
        "bank_net_mills": bank_mills,
        "platform_net": format_mills(platform_mills),
        "bank_net": format_mills(bank_mills),
        "amount_impact_cents": impact_cents,
        "delta": impact_cents,
        "amount_impact": format_cents(impact_cents),
        "rule_fired": rule,
        "rule": rule,
        "reason": reason,
        "detail": reason,
        "confidence": confidence,
        "needs_human_review": needs_review,
    }
    if extra:
        result.update(extra)
    return result


def _canonicalize(
    rows: list[dict[str, str]], source: str
) -> tuple[list[dict[str, str]], list[dict[str, object]], set[str]]:
    grouped: dict[str, dict[tuple[tuple[str, str], ...], list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        grouped[row["txn_id"]][_signature(row)].append(row)

    canonical: list[dict[str, str]] = []
    duplicate_findings: list[dict[str, object]] = []
    ambiguous_ids: set[str] = set()
    category = "DUPLICATE_PLATFORM" if source == "platform" else "DUPLICATE_BANK"
    for txn_id in sorted(grouped):
        signatures = grouped[txn_id]
        if len(signatures) > 1:
            ambiguous_ids.add(txn_id)
        for signature in sorted(signatures):
            copies = sorted(signatures[signature], key=lambda row: row["row_id"])
            canonical.append(copies[0])
            for duplicate in copies[1:]:
                cents = mills_to_cents(parse_mills(duplicate["net_amount"]))
                impact = cents if source == "platform" else -cents
                duplicate_findings.append(
                    _record(
                        category,
                        platform_row=duplicate if source == "platform" else None,
                        bank_row=duplicate if source == "bank" else None,
                        impact_cents=impact,
                        rule="A9",
                        reason=(
                            f"An identical {source} submission repeats txn_id {txn_id}; "
                            f"canonical row is {copies[0]['row_id']}."
                        ),
                        extra={"canonical_row_id": copies[0]["row_id"]},
                    )
                )
    return (
        sorted(canonical, key=lambda row: row["row_id"]),
        duplicate_findings,
        ambiguous_ids,
    )


def reconcile(
    platform: list[dict[str, str]], bank: list[dict[str, str]]
) -> dict[str, object]:
    """Classify each source row once, then add batch-level rounding findings."""
    classes: list[dict[str, object]] = []
    canonical_platform, platform_duplicates, platform_ambiguous = _canonicalize(
        platform, "platform"
    )
    canonical_bank, bank_duplicates, bank_ambiguous = _canonicalize(bank, "bank")
    ambiguous_txn_ids = platform_ambiguous | bank_ambiguous
    classes.extend(platform_duplicates)
    classes.extend(bank_duplicates)

    captures = {
        row["txn_id"] for row in canonical_platform if row["status"] == "capture"
    }
    orphan_ids = {
        row["row_id"]
        for row in canonical_platform
        if row["status"] == "refund"
        and row.get("original_txn_id", "") not in captures
    }
    for row in canonical_platform:
        if row["row_id"] in orphan_ids:
            classes.append(
                _record(
                    "ORPHAN_REFUND",
                    platform_row=row,
                    impact_cents=mills_to_cents(parse_mills(row["net_amount"])),
                    rule="A10",
                    reason=(
                        f"Refund references {row.get('original_txn_id', '')}, "
                        "which has no capture in the platform data."
                    ),
                    confidence="high",
                )
            )

    matched_platform: set[str] = set()
    matched_bank: set[str] = set()
    matched_pairs: list[tuple[dict[str, str], dict[str, str]]] = []

    def eligible(
        p_row: dict[str, str], b_row: dict[str, str], *, require_amount: bool
    ) -> bool:
        if b_row["row_id"] in matched_bank:
            return False
        if (
            b_row["currency"] != p_row["currency"]
            or b_row["status"] != p_row["status"]
            or b_row["customer_id"] != p_row["customer_id"]
        ):
            return False
        created_day = _day(p_row["created_at"])
        settled_day = _day(b_row["settled_at"])
        if not created_day <= settled_day <= created_day + timedelta(days=2):
            return False
        delta = abs(
            mills_to_cents(parse_mills(p_row["net_amount"]))
            - mills_to_cents(parse_mills(b_row["net_amount"]))
        )
        return not require_amount or delta <= TOLERANCE_CENTS

    platform_candidates = [
        row for row in canonical_platform if row["row_id"] not in orphan_ids
    ]
    for p_row in platform_candidates:
        same_ref = [
            row
            for row in canonical_bank
            if p_row.get("bank_ref")
            and p_row.get("bank_ref") == row.get("bank_ref")
            and eligible(p_row, row, require_amount=False)
        ]
        exact_eligible = [
            row for row in same_ref if eligible(p_row, row, require_amount=True)
        ]
        other_eligible = [
            row
            for row in canonical_bank
            if row not in same_ref and eligible(p_row, row, require_amount=True)
        ]
        candidate = None
        matching_rule = "A7, A8"
        if exact_eligible:
            candidate = min(
                exact_eligible,
                key=lambda row: (
                    abs(
                        mills_to_cents(parse_mills(p_row["net_amount"]))
                        - mills_to_cents(parse_mills(row["net_amount"]))
                    ),
                    row["row_id"],
                ),
            )
            matching_rule = "A7 exact bank_ref, A8 date/customer/currency"
        elif other_eligible:
            candidate = min(
                other_eligible,
                key=lambda row: (
                    abs(
                        mills_to_cents(parse_mills(p_row["net_amount"]))
                        - mills_to_cents(parse_mills(row["net_amount"]))
                    ),
                    row["row_id"],
                ),
            )
            matching_rule = "A7 fuzzy amount/customer/currency, A8 date window"
        if candidate is None:
            continue

        matched_platform.add(p_row["row_id"])
        matched_bank.add(candidate["row_id"])
        matched_pairs.append((p_row, candidate))
        p_cents = mills_to_cents(parse_mills(p_row["net_amount"]))
        b_cents = mills_to_cents(parse_mills(candidate["net_amount"]))
        delta_cents = p_cents - b_cents
        late = _month(candidate["settled_at"]) > _month(p_row["created_at"])
        category = "TIMING_NEXT_MONTH" if late else "MATCHED"
        impact = p_cents if late else delta_cents
        reason = (
            "The settlement arrives after the transaction cohort's month-end cutoff."
            if late
            else (
                f"Matched within the one-cent tolerance; platform minus bank is "
                f"{format_cents(delta_cents)}."
                if delta_cents
                else "Matched to the bank settlement with no cent-level difference."
            )
        )
        ambiguous = (
            len(exact_eligible) > 1
            or bool(set((p_row["txn_id"], candidate["txn_id"])) & ambiguous_txn_ids)
        )
        if ambiguous:
            reason += " The transaction ID has distinct same-source records; review is required."
        classes.append(
            _record(
                category,
                p_row,
                candidate,
                impact_cents=impact,
                rule=("A1, A7, A8, A12, A13" if late else matching_rule),
                reason=reason,
                confidence="low" if ambiguous else "high",
                needs_review=ambiguous,
            )
        )

    for row in canonical_platform:
        if row["row_id"] in orphan_ids or row["row_id"] in matched_platform:
            continue
        p_cents = mills_to_cents(parse_mills(row["net_amount"]))
        ref_candidates = [
            bank_row
            for bank_row in canonical_bank
            if row.get("bank_ref")
            and bank_row.get("bank_ref") == row.get("bank_ref")
            and bank_row["row_id"] not in matched_bank
            and bank_row["currency"] == row["currency"]
            and bank_row["customer_id"] == row["customer_id"]
            and bank_row["status"] == row["status"]
            and row["created_at"]
            and bank_row["settled_at"]
            and _day(row["created_at"])
            <= _day(bank_row["settled_at"])
            <= _day(row["created_at"]) + timedelta(days=2)
        ]
        reference_mismatch = any(
            abs(
                p_cents - mills_to_cents(parse_mills(bank_row["net_amount"]))
            )
            > TOLERANCE_CENTS
            for bank_row in ref_candidates
        )
        mismatch = row["txn_id"] in ambiguous_txn_ids or reference_mismatch
        category = "AMOUNT_MISMATCH" if mismatch else "UNMATCHED_PLATFORM"
        classes.append(
            _record(
                category,
                platform_row=row,
                impact_cents=p_cents,
                rule="A7, A8",
                reason=(
                    "A same-reference settlement exists but its amount exceeds the "
                    "one-cent tolerance."
                    if reference_mismatch
                    else (
                        "This transaction ID has distinct platform records with "
                        "different business values."
                        if mismatch
                        else "No eligible bank settlement was found for this platform row."
                    )
                ),
                confidence="low" if mismatch else "medium",
                needs_review=mismatch,
            )
        )

    for row in canonical_bank:
        if row["row_id"] in matched_bank:
            continue
        b_cents = mills_to_cents(parse_mills(row["net_amount"]))
        ref_candidates = [
            platform_row
            for platform_row in canonical_platform
            if row.get("bank_ref")
            and platform_row.get("bank_ref") == row.get("bank_ref")
            and platform_row["row_id"] not in matched_platform
            and platform_row["row_id"] not in orphan_ids
            and platform_row["currency"] == row["currency"]
            and platform_row["customer_id"] == row["customer_id"]
            and platform_row["status"] == row["status"]
            and platform_row["created_at"]
            and row["settled_at"]
            and _day(platform_row["created_at"])
            <= _day(row["settled_at"])
            <= _day(platform_row["created_at"]) + timedelta(days=2)
        ]
        reference_mismatch = any(
            abs(
                mills_to_cents(parse_mills(platform_row["net_amount"])) - b_cents
            )
            > TOLERANCE_CENTS
            for platform_row in ref_candidates
        )
        mismatch = row["txn_id"] in ambiguous_txn_ids or reference_mismatch
        classes.append(
            _record(
                "AMOUNT_MISMATCH" if mismatch else "UNMATCHED_BANK",
                bank_row=row,
                impact_cents=-b_cents,
                rule="A7, A8, A13",
                reason=(
                    "A same-reference platform transaction exists but its amount "
                    "exceeds the one-cent tolerance."
                    if reference_mismatch
                    else (
                        "This transaction ID has distinct bank records with "
                        "different business values."
                        if mismatch
                        else "No eligible platform transaction was found for this bank row."
                    )
                ),
                confidence="low" if mismatch else "medium",
                needs_review=mismatch,
            )
        )

    batch_groups: dict[
        tuple[str, str, str], list[tuple[dict[str, str], dict[str, str]]]
    ] = defaultdict(list)
    for p_row, b_row in matched_pairs:
        if _month(b_row["settled_at"]) != _month(p_row["created_at"]):
            continue
        if p_row["settlement_batch_id"] != b_row["settlement_batch_id"]:
            continue
        if mills_to_cents(parse_mills(p_row["net_amount"])) != mills_to_cents(
            parse_mills(b_row["net_amount"])
        ):
            continue
        batch_groups[
            (
                p_row["settlement_batch_id"],
                p_row["currency"],
                _month(b_row["settled_at"]),
            )
        ].append((p_row, b_row))

    for (batch_id, currency, month), pairs in sorted(batch_groups.items()):
        platform_mills = sum(parse_mills(p["net_amount"]) for p, _ in pairs)
        bank_mills = sum(parse_mills(b["net_amount"]) for _, b in pairs)
        impact = mills_to_cents(platform_mills) - mills_to_cents(bank_mills)
        if not impact:
            continue
        txn_ids = sorted({p["txn_id"] for p, _ in pairs})
        classes.append(
            _record(
                "ROUNDING_DIFFERENCE",
                impact_cents=impact,
                rule="A3, A11, A13",
                reason=(
                    f"{len(pairs)} row pairs match when rounded individually, but "
                    f"the source-precision batch sums differ by {format_cents(impact)}."
                ),
                extra={
                    "txn_ids": txn_ids,
                    "txn_id": None,
                    "batch_id": batch_id,
                    "currency": currency,
                    "platform_net_mills": platform_mills,
                    "bank_net_mills": bank_mills,
                    "platform_net": format_mills(platform_mills),
                    "bank_net": format_mills(bank_mills),
                    "source_row_ids": {
                        "platform": sorted(p["row_id"] for p, _ in pairs),
                        "bank": sorted(b["row_id"] for _, b in pairs),
                    },
                    "aggregate_month": month,
                },
            )
        )

    return {
        "classifications": sorted(
            classes,
            key=lambda row: (
                str(row["category"]),
                str(row.get("txn_id") or ""),
                str(row.get("platform_row_id") or ""),
                str(row.get("bank_row_id") or ""),
                str(row.get("batch_id") or ""),
            ),
        )
    }


def build_report(
    platform: list[dict[str, str]], bank: list[dict[str, str]]
) -> dict[str, object]:
    result = reconcile(platform, bank)
    classes = result["classifications"]
    months = sorted(
        {_month(row["created_at"]) for row in platform + bank if row.get("created_at")}
    )
    platform_total_mills = sum(
        parse_mills(row["net_amount"]) for row in platform
    )
    # Include each bank row only if it settled by the last day of its creation month.
    bank_total_mills = 0
    for row in bank:
        if not row.get("settled_at") or not row.get("created_at"):
            continue
        month = _month(row["created_at"])
        year, month_number = (int(part) for part in month.split("-"))
        if month_number == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month_number + 1, 1)
        cutoff_day = next_month - timedelta(days=1)
        if _day(row["settled_at"]) <= cutoff_day:
            bank_total_mills += parse_mills(row["net_amount"])

    platform_total = mills_to_cents(platform_total_mills)
    bank_total = mills_to_cents(bank_total_mills)
    explained_delta = sum(
        int(row["amount_impact_cents"])
        for row in classes
        if row["category"] != "ROUNDING_DIFFERENCE"
    )
    rounding_residual = sum(
        int(row["amount_impact_cents"])
        for row in classes
        if row["category"] == "ROUNDING_DIFFERENCE"
    )
    variance = platform_total - bank_total
    unexplained = variance - explained_delta - rounding_residual
    counts = Counter(str(row["category"]) for row in classes)
    summary = {
        "months": months,
        "currency": "USD",
        "platform_total": format_cents(platform_total),
        "bank_total": format_cents(bank_total),
        "variance": format_cents(variance),
        "explained_delta": format_cents(explained_delta),
        "rounding_residual": format_cents(rounding_residual),
        "unexplained_delta": format_cents(unexplained),
        "conservation_holds": abs(unexplained) < 1,
        "platform_total_cents": platform_total,
        "bank_total_cents": bank_total,
        "variance_cents": variance,
        "explained_delta_cents": explained_delta,
        "rounding_residual_cents": rounding_residual,
        "unexplained_delta_cents": unexplained,
        "classification_counts": dict(sorted(counts.items())),
    }
    return {
        "summary": summary,
        "classifications": classes,
        "assumption_reference": "See ASSUMPTIONS.md; findings include the rule IDs that fired.",
    }


def write_report(report: dict[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reconciliation_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    summary = report["summary"]
    rows = report["classifications"]
    counts = summary["classification_counts"]
    lines = [
        "# Reconciliation report",
        "",
        f"Reporting cohorts: {', '.join(summary['months']) or 'none'} ({summary['currency']}, UTC month-end cutoffs).",
        "",
        "| Summary | Amount |",
        "|---|---:|",
        f"| Platform total | {summary['platform_total']} {summary['currency']} |",
        f"| Bank total (settled by each cohort cutoff) | {summary['bank_total']} {summary['currency']} |",
        f"| Platform minus bank variance | {summary['variance']} {summary['currency']} |",
        f"| Explained transaction deltas | {summary['explained_delta']} {summary['currency']} |",
        f"| Batch rounding residual | {summary['rounding_residual']} {summary['currency']} |",
        f"| Unexplained residual | {summary['unexplained_delta']} {summary['currency']} |",
        "",
        "Conservation check: `platform_total - bank_total - explained_delta - rounding_residual = unexplained_delta`.",
        f"**Conservation holds (< $0.01 unexplained): {summary['conservation_holds']}**",
        "",
        "## Classification breakdown",
        "",
        "| Category | Findings | Example txn ID / batch |",
        "|---|---:|---|",
    ]
    for category in BUCKETS:
        selected = [row for row in rows if row["category"] == category]
        examples = [
            str(row.get("txn_id") or row.get("batch_id") or "—")
            for row in selected[:3]
        ]
        lines.append(
            f"| {category} | {counts.get(category, 0)} | {', '.join(examples) or '—'} |"
        )
    lines.extend(
        [
            "",
            "Every finding records its category, transaction IDs, signed cent impact, rule, plain-English reason, confidence, and human-review flag.",
        ]
    )
    (output_dir / "reconciliation_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
