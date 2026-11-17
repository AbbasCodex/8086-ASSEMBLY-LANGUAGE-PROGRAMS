from __future__ import annotations

import inspect
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_generator import generate_data
from demo import planted_gap_metrics
from reconcile import build_report, reconcile
import export_static


def _row(
    row_id: str,
    txn_id: str,
    created: str,
    settled: str,
    *,
    net: str = "9.700",
    status: str = "capture",
    original: str = "",
    ref: str | None = None,
    batch: str = "BATCH-TEST",
) -> dict[str, str]:
    return {
        "row_id": row_id,
        "txn_id": txn_id,
        "customer_id": "C0001",
        "amount": "10.000",
        "currency": "USD",
        "created_at": f"{created}T12:00:00+00:00",
        "status": status,
        "original_txn_id": original,
        "bank_ref": ref if ref is not None else f"REF-{txn_id}",
        "settled_at": f"{settled}T12:00:00+00:00" if settled else "",
        "settlement_batch_id": batch,
        "fee": "0.300",
        "net_amount": net,
    }


def _categories(platform, bank):
    return reconcile(platform, bank)["classifications"]


def _category(rows, category):
    return [row for row in rows if row["category"] == category]


def test_reconciler_api_has_no_ground_truth_dependency():
    source = (ROOT / "reconcile.py").read_text(encoding="utf-8").lower()
    assert "manifest" not in source
    assert "manifest" not in inspect.signature(reconcile).parameters
    assert "manifest" not in inspect.signature(build_report).parameters


def test_full_pipeline_detects_planted_cases_across_ten_seeds_without_false_positives(
    tmp_path: Path,
):
    expected_gap_categories = {
        "TIMING_NEXT_MONTH",
        "ROUNDING_DIFFERENCE",
        "DUPLICATE_PLATFORM",
        "ORPHAN_REFUND",
    }
    for seed in range(10):
        output = tmp_path / str(seed)
        manifest = generate_data(output, seed=seed)
        import csv

        with (output / "platform_transactions.csv").open(newline="", encoding="utf-8") as f:
            platform = list(csv.DictReader(f))
        with (output / "bank_settlements.csv").open(newline="", encoding="utf-8") as f:
            bank = list(csv.DictReader(f))
        report = build_report(platform, bank)
        findings = report["classifications"]
        metrics = planted_gap_metrics(findings, manifest)
        assert metrics == {
            "true_positive": 4,
            "false_positive": 0,
            "false_negative": 0,
            "precision_percent": 100,
            "recall_percent": 100,
        }
        planted = manifest["planted_gaps"]
        timing = planted["timing_next_month"]
        duplicate = planted["duplicate_platform"]
        orphan = planted["orphan_refund"]
        rounding = planted["rounding_difference"]
        controls = manifest["control_anomalies"]

        assert any(
            row["category"] == "TIMING_NEXT_MONTH"
            and row["platform_row_id"] == timing["platform_row_id"]
            and row["bank_row_id"] == timing["bank_row_id"]
            for row in findings
        )
        assert any(
            row["category"] == "DUPLICATE_PLATFORM"
            and row["platform_row_id"] in duplicate["row_ids"]
            for row in findings
        )
        assert any(
            row["category"] == "ORPHAN_REFUND"
            and row["platform_row_id"] in orphan["row_ids"]
            for row in findings
        )
        assert any(
            row["category"] == "ROUNDING_DIFFERENCE"
            and row["batch_id"] == rounding["batch_id"]
            and set(row["source_row_ids"]["platform"]) == set(rounding["platform_row_ids"])
            and set(row["source_row_ids"]["bank"]) == set(rounding["bank_row_ids"])
            for row in findings
        )

        nonmatched = [row for row in findings if row["category"] != "MATCHED"]
        actual_findings = {
            (
                row["category"],
                row.get("platform_row_id"),
                row.get("bank_row_id"),
                row.get("batch_id") if row["category"] == "ROUNDING_DIFFERENCE" else None,
            )
            for row in nonmatched
        }
        expected_findings = {
            (
                "TIMING_NEXT_MONTH",
                timing["platform_row_id"],
                timing["bank_row_id"],
                None,
            ),
            ("DUPLICATE_PLATFORM", duplicate["row_ids"][0], None, None),
            ("ORPHAN_REFUND", orphan["row_ids"][0], None, None),
            ("ROUNDING_DIFFERENCE", None, None, rounding["batch_id"]),
            (
                "DUPLICATE_BANK",
                None,
                controls["duplicate_bank"]["row_ids"][0],
                None,
            ),
            (
                "UNMATCHED_BANK",
                None,
                controls["unmatched_bank"]["row_ids"][0],
                None,
            ),
        }
        assert actual_findings == expected_findings
        assert report["summary"]["unexplained_delta_cents"] == 0
        assert report["summary"]["conservation_holds"]
        assert Counter(
            row["platform_row_id"]
            for row in findings
            if row["platform_row_id"] is not None
        ) == Counter(row["row_id"] for row in platform)
        assert Counter(
            row["bank_row_id"] for row in findings if row["bank_row_id"] is not None
        ) == Counter(row["row_id"] for row in bank)

        found = {
            "TIMING_NEXT_MONTH": sum(
                row["category"] == "TIMING_NEXT_MONTH"
                and row["platform_row_id"] == timing["platform_row_id"]
                for row in findings
            ),
            "DUPLICATE_PLATFORM": sum(
                row["category"] == "DUPLICATE_PLATFORM"
                and row["platform_row_id"] in duplicate["row_ids"]
                for row in findings
            ),
            "ORPHAN_REFUND": sum(
                row["category"] == "ORPHAN_REFUND"
                and row["platform_row_id"] in orphan["row_ids"]
                for row in findings
            ),
            "ROUNDING_DIFFERENCE": sum(
                row["category"] == "ROUNDING_DIFFERENCE"
                and row["batch_id"] == rounding["batch_id"]
                for row in findings
            ),
        }
        assert set(found) == expected_gap_categories
        assert all(found.values())
        assert all(
            row["category"] not in expected_gap_categories
            or (
                row["category"] == "TIMING_NEXT_MONTH"
                and row["platform_row_id"] == timing["platform_row_id"]
            )
            or (
                row["category"] == "DUPLICATE_PLATFORM"
                and row["platform_row_id"] in duplicate["row_ids"]
            )
            or (
                row["category"] == "ORPHAN_REFUND"
                and row["platform_row_id"] in orphan["row_ids"]
            )
            or (
                row["category"] == "ROUNDING_DIFFERENCE"
                and row["batch_id"] == rounding["batch_id"]
            )
            for row in findings
        )


def test_empty_files_have_zero_totals_and_no_findings():
    report = build_report([], [])
    assert report["classifications"] == []
    assert report["summary"]["platform_total_cents"] == 0
    assert report["summary"]["bank_total_cents"] == 0
    assert report["summary"]["unexplained_delta_cents"] == 0
    assert report["summary"]["conservation_holds"]


def test_clean_dataset_has_matches_only_and_zero_unexplained():
    platform = [_row("P1", "T1", "2025-04-10", "2025-04-11")]
    bank = [_row("B1", "T1", "2025-04-10", "2025-04-11")]
    report = build_report(platform, bank)
    assert {row["category"] for row in report["classifications"]} == {"MATCHED"}
    assert report["summary"]["unexplained_delta_cents"] == 0


def test_identical_duplicate_and_late_settlement_are_distinct_single_findings():
    platform = [
        _row("P1", "T1", "2025-10-31", "2025-11-01"),
        _row("P2", "T1", "2025-10-31", "2025-11-01"),
    ]
    bank = [_row("B1", "T1", "2025-10-31", "2025-11-01")]
    findings = _categories(platform, bank)
    assert len(_category(findings, "TIMING_NEXT_MONTH")) == 1
    assert len(_category(findings, "DUPLICATE_PLATFORM")) == 1
    report = build_report(platform, bank)
    assert report["summary"]["unexplained_delta_cents"] == 0
    assert report["summary"]["explained_delta_cents"] == 1940


def test_october_month_end_and_november_first_cutoffs():
    platform = [
        _row("P1", "T1", "2025-10-29", "2025-10-31"),
        _row("P2", "T2", "2025-10-31", "2025-11-01"),
    ]
    bank = [
        _row("B1", "T1", "2025-10-29", "2025-10-31"),
        _row("B2", "T2", "2025-10-31", "2025-11-01"),
    ]
    findings = _categories(platform, bank)
    assert len(_category(findings, "MATCHED")) == 1
    assert len(_category(findings, "TIMING_NEXT_MONTH")) == 1
    assert _category(findings, "TIMING_NEXT_MONTH")[0]["txn_id"] == "T2"


def test_weekend_and_holiday_settlement_dates_use_calendar_day_window():
    platform = [
        _row("P1", "WEEKEND", "2025-01-03", "2025-01-05"),
        _row("P2", "HOLIDAY", "2025-12-24", "2025-12-26"),
    ]
    bank = [
        _row("B1", "WEEKEND", "2025-01-03", "2025-01-05"),
        _row("B2", "HOLIDAY", "2025-12-24", "2025-12-26"),
    ]
    findings = _categories(platform, bank)
    assert len(_category(findings, "MATCHED")) == 2
    assert not _category(findings, "UNMATCHED_PLATFORM")
    assert not _category(findings, "UNMATCHED_BANK")


def test_bank_side_identical_duplicate_is_detected():
    platform = [_row("P1", "T1", "2025-04-10", "2025-04-11")]
    bank = [
        _row("B1", "T1", "2025-04-10", "2025-04-11"),
        _row("B2", "T1", "2025-04-10", "2025-04-11"),
    ]
    findings = _categories(platform, bank)
    assert len(_category(findings, "DUPLICATE_BANK")) == 1
    assert _category(findings, "DUPLICATE_BANK")[0]["bank_row_id"] == "B2"


def test_same_txn_id_with_different_amount_is_not_an_exact_duplicate():
    platform = [_row("P1", "T1", "2025-04-10", "2025-04-11", net="9.700")]
    bank = [_row("B1", "T1", "2025-04-10", "2025-04-11", net="8.000")]
    findings = _categories(platform, bank)
    assert not _category(findings, "DUPLICATE_PLATFORM")
    assert not _category(findings, "DUPLICATE_BANK")
    mismatches = _category(findings, "AMOUNT_MISMATCH")
    assert len(mismatches) == 2
    assert all(row["needs_human_review"] for row in mismatches)
    assert all(row["confidence"] == "low" for row in mismatches)
    assert build_report(platform, bank)["summary"]["unexplained_delta_cents"] == 0


def test_distinct_same_source_values_are_not_duplicates_and_need_review():
    platform = [
        _row("P1", "T1", "2025-04-10", "2025-04-11", net="9.700"),
        _row("P2", "T1", "2025-04-10", "2025-04-11", net="8.000"),
    ]
    bank = [_row("B1", "T1", "2025-04-10", "2025-04-11", net="9.700")]
    findings = _categories(platform, bank)
    assert not _category(findings, "DUPLICATE_PLATFORM")
    assert len(_category(findings, "MATCHED")) == 1
    assert len(_category(findings, "AMOUNT_MISMATCH")) == 1
    assert all(row["needs_human_review"] for row in findings)
    assert all(row["confidence"] == "low" for row in findings)
    assert build_report(platform, bank)["summary"]["unexplained_delta_cents"] == 0


def test_each_finding_has_explainability_and_review_fields():
    platform = [_row("P1", "T1", "2025-04-10", "2025-04-11", net="9.700")]
    bank = [_row("B1", "T1", "2025-04-10", "2025-04-11", net="8.000")]
    findings = _categories(platform, bank)
    required = {
        "category",
        "txn_ids",
        "amount_impact_cents",
        "rule_fired",
        "reason",
        "confidence",
        "needs_human_review",
    }
    assert findings
    assert all(required <= row.keys() for row in findings)
    assert all(isinstance(row["amount_impact_cents"], int) for row in findings)
    assert all(row["rule_fired"] and row["reason"] for row in findings)
    assert all(row["confidence"] in {"high", "medium", "low"} for row in findings)


def test_refund_parent_in_prior_month_is_not_orphan():
    platform = [
        _row("P1", "PARENT", "2025-10-31", "2025-11-01", net="10.000"),
        _row(
            "P2",
            "REFUND",
            "2025-11-01",
            "2025-11-02",
            net="-3.000",
            status="refund",
            original="PARENT",
        ),
    ]
    bank = [
        _row("B1", "PARENT", "2025-10-31", "2025-11-01", net="10.000"),
        _row(
            "B2",
            "REFUND",
            "2025-11-01",
            "2025-11-02",
            net="-3.000",
            status="refund",
            original="PARENT",
        ),
    ]
    findings = _categories(platform, bank)
    assert not _category(findings, "ORPHAN_REFUND")
    assert any(row["txn_id"] == "REFUND" and row["category"] == "MATCHED" for row in findings)


def test_partial_refund_with_existing_parent_is_valid_and_matches():
    platform = [
        _row("P1", "PARENT", "2025-04-10", "2025-04-11", net="10.000"),
        _row(
            "P2",
            "REFUND",
            "2025-04-12",
            "2025-04-13",
            net="-3.000",
            status="refund",
            original="PARENT",
        ),
    ]
    bank = [
        _row("B1", "PARENT", "2025-04-10", "2025-04-11", net="10.000"),
        _row(
            "B2",
            "REFUND",
            "2025-04-12",
            "2025-04-13",
            net="-3.000",
            status="refund",
            original="PARENT",
        ),
    ]
    findings = _categories(platform, bank)
    assert len(_category(findings, "MATCHED")) == 2
    assert not _category(findings, "ORPHAN_REFUND")
    assert build_report(platform, bank)["summary"]["unexplained_delta_cents"] == 0


def test_shuffling_input_rows_produces_identical_report(tmp_path: Path):
    manifest = generate_data(tmp_path, seed=2026)
    import csv

    with (tmp_path / "platform_transactions.csv").open(newline="", encoding="utf-8") as f:
        platform = list(csv.DictReader(f))
    with (tmp_path / "bank_settlements.csv").open(newline="", encoding="utf-8") as f:
        bank = list(csv.DictReader(f))
    baseline = build_report(platform, bank)
    random.Random(42).shuffle(platform)
    random.Random(43).shuffle(bank)
    assert build_report(platform, bank) == baseline
    assert json.loads(json.dumps(manifest))["seed"] == 2026


def test_rounding_is_detected_only_at_aggregate_level(tmp_path: Path):
    manifest = generate_data(tmp_path, seed=86420)
    import csv

    with (tmp_path / "platform_transactions.csv").open(newline="", encoding="utf-8") as f:
        platform = list(csv.DictReader(f))
    with (tmp_path / "bank_settlements.csv").open(newline="", encoding="utf-8") as f:
        bank = list(csv.DictReader(f))
    report = build_report(platform, bank)
    txn_ids = set(manifest["planted_gaps"]["rounding_difference"]["txn_ids"])
    transaction_results = [
        row for row in report["classifications"]
        if set(row["txn_ids"]) & txn_ids and row["category"] != "ROUNDING_DIFFERENCE"
    ]
    assert all(row["category"] == "MATCHED" for row in transaction_results)
    aggregate = _category(report["classifications"], "ROUNDING_DIFFERENCE")
    assert len(aggregate) == 1
    assert aggregate[0]["amount_impact_cents"] == 4


def test_static_export_is_one_self_contained_html_file(tmp_path: Path, monkeypatch):
    platform = [_row("P1", "T1", "2025-04-10", "2025-04-11")]
    bank = [_row("B1", "T1", "2025-04-10", "2025-04-11")]
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "docs" / "index.html"
    report_path.write_text(json.dumps(build_report(platform, bank)), encoding="utf-8")
    monkeypatch.setattr(export_static, "REPORT", report_path)
    monkeypatch.setattr(export_static, "OUTPUT", output_path)

    export_static.main()
    html = output_path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "report-data" in html
    assert "data-sort" in html
    assert "download-category" in html
    assert "waterfall" in html.lower()
    assert "https://" not in html
    assert "src=\"http" not in html
    assert list(output_path.parent.iterdir()) == [output_path]
