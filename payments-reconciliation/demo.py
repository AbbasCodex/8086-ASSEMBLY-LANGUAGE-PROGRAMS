"""Regenerate the deterministic fixture and print its reconciliation report."""

from __future__ import annotations

import json
from pathlib import Path

from data_generator import generate_data
from reconcile import build_report, read_csv, write_report

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PLANTED_CATEGORIES = {
    "TIMING_NEXT_MONTH",
    "ROUNDING_DIFFERENCE",
    "DUPLICATE_PLATFORM",
    "ORPHAN_REFUND",
}


def planted_gap_metrics(
    classifications: list[dict[str, object]], manifest: dict[str, object]
) -> dict[str, int]:
    planted = manifest["planted_gaps"]
    expected = {
        (
            "TIMING_NEXT_MONTH",
            planted["timing_next_month"]["platform_row_id"],
            planted["timing_next_month"]["bank_row_id"],
            "",
        ),
        (
            "ROUNDING_DIFFERENCE",
            "",
            "",
            planted["rounding_difference"]["batch_id"],
        ),
        (
            "DUPLICATE_PLATFORM",
            planted["duplicate_platform"]["row_ids"][0],
            "",
            "",
        ),
        (
            "ORPHAN_REFUND",
            planted["orphan_refund"]["row_ids"][0],
            "",
            "",
        ),
    }
    detected = {
        (
            str(row["category"]),
            str(row.get("platform_row_id") or ""),
            str(row.get("bank_row_id") or ""),
            str(row.get("batch_id") or "")
            if row["category"] == "ROUNDING_DIFFERENCE"
            else "",
        )
        for row in classifications
        if row["category"] in PLANTED_CATEGORIES
    }
    true_positive = len(expected & detected)
    false_positive = len(detected - expected)
    false_negative = len(expected - detected)
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision_percent": (
            true_positive * 100 // precision_denominator
            if precision_denominator
            else 100
        ),
        "recall_percent": (
            true_positive * 100 // recall_denominator
            if recall_denominator
            else 100
        ),
    }


def main() -> None:
    manifest = generate_data(DATA)
    report = build_report(
        read_csv(DATA / "platform_transactions.csv"),
        read_csv(DATA / "bank_settlements.csv"),
    )
    write_report(report, DATA)
    summary = report["summary"]
    metrics = planted_gap_metrics(report["classifications"], manifest)
    print("Reconciliation summary")
    print("----------------------")
    print(f"Platform total:    {summary['platform_total']} {summary['currency']}")
    print(f"Bank total:        {summary['bank_total']} {summary['currency']}")
    print(f"Variance:          {summary['variance']} {summary['currency']}")
    print(f"Explained deltas:  {summary['explained_delta']} {summary['currency']}")
    print(f"Rounding residual: {summary['rounding_residual']} {summary['currency']}")
    print(f"Unexplained:       {summary['unexplained_delta']} {summary['currency']}")
    print(f"Conservation holds: {summary['conservation_holds']}")
    print(
        "Planted-gap precision/recall: "
        f"{metrics['precision_percent']}% / {metrics['recall_percent']}% "
        f"(TP={metrics['true_positive']}, FP={metrics['false_positive']}, "
        f"FN={metrics['false_negative']})"
    )
    print("\nPlanted ground-truth row IDs:")
    print(json.dumps(manifest, indent=2))
    print(f"\nFull report: {DATA / 'reconciliation_report.md'}")


if __name__ == "__main__":
    main()
