"""Seeded synthetic payment and settlement data for the reconciliation demo."""

from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

SEED = 86420
FIELDS = [
    "row_id",
    "txn_id",
    "customer_id",
    "amount",
    "currency",
    "created_at",
    "status",
    "original_txn_id",
    "bank_ref",
    "settled_at",
    "settlement_batch_id",
    "fee",
    "net_amount",
]


def _stamp(day: date, hour: int = 12) -> str:
    return datetime.combine(day, time(hour=hour), tzinfo=timezone.utc).isoformat()


def _money(mills: int) -> str:
    sign = "-" if mills < 0 else ""
    dollars, remainder = divmod(abs(mills), 1000)
    return f"{sign}{dollars}.{remainder:03d}"


def _batch(day: date) -> str:
    return f"BATCH-{day:%Y%m%d}-USD"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def generate_data(output_dir: Path, seed: int = SEED) -> dict:
    """Create two months of transactions plus deterministic planted cases."""
    rng = random.Random(seed)
    platform: list[dict[str, str]] = []
    bank: list[dict[str, str]] = []
    manifest: dict[str, object] = {
        "seed": seed,
        "reporting_months": ["2025-01", "2025-02"],
        "planted_gaps": {},
        "control_anomalies": {},
    }

    rounding_ids: list[str] = []
    timing_txn_id = ""
    timing_row_id = ""
    next_txn = 1
    next_platform_row = 1
    next_bank_row = 1

    for month in (1, 2):
        for day_number in range(2, 27):
            for _ in range(40):
                txn_number = next_txn
                txn_id = f"TX{txn_number:06d}"
                customer = f"C{rng.randint(1, 800):04d}"
                created_day = date(2025, month, day_number)
                settled_day = created_day + timedelta(days=rng.choice((1, 2)))
                amount_cents = rng.randint(300, 25000)
                fee_base, fee_remainder = divmod(amount_cents * 29, 1000)
                if fee_remainder > 500 or (
                    fee_remainder == 500 and fee_base % 2 == 1
                ):
                    fee_base += 1
                fee_cents = fee_base + 30
                amount_mills = amount_cents * 10
                fee_mills = fee_cents * 10
                net_mills = amount_mills - fee_mills
                ref = f"REF-{txn_id}"
                batch = _batch(settled_day)

                is_rounding_row = (
                    month == 1 and day_number == 10 and len(rounding_ids) < 40
                )
                if is_rounding_row:
                    amount_mills = 10500
                    fee_mills = 496
                    net_mills = 10004
                    settled_day = created_day + timedelta(days=1)
                    batch = "BATCH-ROUNDING-20250111-USD"
                    rounding_ids.append(txn_id)

                is_timing = month == 2 and day_number == 2 and timing_txn_id == ""
                if is_timing:
                    created_day = date(2025, 2, 28)
                    settled_day = date(2025, 3, 1)
                    batch = _batch(settled_day)
                    timing_txn_id = txn_id

                platform_row = {
                    "row_id": f"P{next_platform_row:06d}",
                    "txn_id": txn_id,
                    "customer_id": customer,
                    "amount": _money(amount_mills),
                    "currency": "USD",
                    "created_at": _stamp(created_day),
                    "status": "capture",
                    "original_txn_id": "",
                    "bank_ref": ref,
                    "settled_at": _stamp(settled_day),
                    "settlement_batch_id": batch,
                    "fee": _money(fee_mills),
                    "net_amount": _money(net_mills),
                }
                bank_net_mills = 10003 if is_rounding_row else net_mills
                bank_fee_mills = amount_mills - bank_net_mills
                bank_row = {
                    **platform_row,
                    "row_id": f"B{next_bank_row:06d}",
                    "fee": _money(bank_fee_mills),
                    "net_amount": _money(bank_net_mills),
                }
                platform.append(platform_row)
                bank.append(bank_row)
                if is_timing:
                    timing_row_id = bank_row["row_id"]
                next_platform_row += 1
                next_bank_row += 1
                next_txn += 1

    duplicate_platform_source = platform[500]
    duplicate_platform = dict(duplicate_platform_source)
    duplicate_platform["row_id"] = f"P{next_platform_row:06d}"
    platform.append(duplicate_platform)
    manifest["planted_gaps"]["duplicate_platform"] = {
        "txn_id": duplicate_platform["txn_id"],
        "row_ids": [duplicate_platform["row_id"]],
        "canonical_row_id": duplicate_platform_source["row_id"],
    }
    next_platform_row += 1

    orphan_txn = f"RF{next_txn:06d}"
    orphan = {
        "row_id": f"P{next_platform_row:06d}",
        "txn_id": orphan_txn,
        "customer_id": "C0999",
        "amount": "7.000",
        "currency": "USD",
        "created_at": _stamp(date(2025, 1, 20), 14),
        "status": "refund",
        "original_txn_id": "TX999999",
        "bank_ref": f"REF-{orphan_txn}",
        "settled_at": "",
        "settlement_batch_id": "",
        "fee": "0.000",
        "net_amount": "-7.000",
    }
    platform.append(orphan)
    manifest["planted_gaps"]["orphan_refund"] = {
        "txn_id": orphan_txn,
        "row_ids": [orphan["row_id"]],
        "original_txn_id": orphan["original_txn_id"],
    }

    duplicate_bank_source = bank[700]
    duplicate_bank = dict(duplicate_bank_source)
    duplicate_bank["row_id"] = f"B{next_bank_row:06d}"
    bank.append(duplicate_bank)
    manifest["control_anomalies"]["duplicate_bank"] = {
        "txn_id": duplicate_bank["txn_id"],
        "row_ids": [duplicate_bank["row_id"]],
        "canonical_row_id": duplicate_bank_source["row_id"],
    }
    next_bank_row += 1

    bank_only_day = date(2025, 1, 18)
    bank_only = {
        "row_id": f"B{next_bank_row:06d}",
        "txn_id": "BANK-ONLY-001",
        "customer_id": "C0888",
        "amount": "25.000",
        "currency": "USD",
        "created_at": _stamp(bank_only_day),
        "status": "capture",
        "original_txn_id": "",
        "bank_ref": "REF-BANK-ONLY-001",
        "settled_at": _stamp(bank_only_day + timedelta(days=1)),
        "settlement_batch_id": _batch(bank_only_day + timedelta(days=1)),
        "fee": "0.750",
        "net_amount": "24.250",
    }
    bank.append(bank_only)
    manifest["control_anomalies"]["unmatched_bank"] = {
        "txn_id": bank_only["txn_id"],
        "row_ids": [bank_only["row_id"]],
    }
    next_bank_row += 1

    tolerance_source = next(
        row for row in platform if row["txn_id"] == "TX001000"
    )
    tolerance_bank = next(
        row for row in bank if row["txn_id"] == tolerance_source["txn_id"]
    )
    tolerance_bank_net_mills = (
        _parse_mills(tolerance_bank["net_amount"]) + 10
    )
    tolerance_bank["net_amount"] = _money(tolerance_bank_net_mills)
    tolerance_bank["fee"] = _money(
        _parse_mills(tolerance_bank["amount"]) - tolerance_bank_net_mills
    )
    manifest["control_anomalies"]["within_tolerance"] = {
        "txn_id": tolerance_source["txn_id"],
        "platform_row_id": tolerance_source["row_id"],
        "bank_row_id": tolerance_bank["row_id"],
        "delta_cents": -1,
    }

    timing_platform = next(row for row in platform if row["txn_id"] == timing_txn_id)
    manifest["planted_gaps"]["timing_next_month"] = {
        "txn_id": timing_txn_id,
        "platform_row_id": timing_platform["row_id"],
        "bank_row_id": timing_row_id,
    }
    rounding_txn_set = set(rounding_ids)
    manifest["planted_gaps"]["rounding_difference"] = {
        "batch_id": "BATCH-ROUNDING-20250111-USD",
        "txn_ids": rounding_ids,
        "platform_row_ids": [
            row["row_id"] for row in platform if row["txn_id"] in rounding_txn_set
        ],
        "bank_row_ids": [
            row["row_id"] for row in bank if row["txn_id"] in rounding_txn_set
        ],
        "platform_net_sum": "400.160",
        "bank_net_sum": "400.120",
        "delta_cents": 4,
    }

    platform.sort(key=lambda row: row["row_id"])
    bank.sort(key=lambda row: row["row_id"])
    _write_csv(output_dir / "platform_transactions.csv", platform)
    _write_csv(output_dir / "bank_settlements.csv", bank)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ground_truth_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _parse_mills(value: str) -> int:
    sign = -1 if value.startswith("-") else 1
    text = value.lstrip("+-")
    whole, _, fraction = text.partition(".")
    return sign * (int(whole) * 1000 + int(fraction.ljust(3, "0") or "0"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    result = generate_data(args.output_dir)
    print(json.dumps(result, indent=2))
