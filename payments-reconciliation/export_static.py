"""Export the latest report as one self-contained GitHub Pages HTML page."""

from __future__ import annotations

import json
from pathlib import Path

from app import render_report

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "data" / "reconciliation_report.json"
OUTPUT = ROOT / "docs" / "index.html"


def main() -> None:
    if not REPORT.exists():
        raise FileNotFoundError("Run `python demo.py` before exporting the static page.")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(render_report(report))
    print(f"Wrote self-contained GitHub Pages site: {OUTPUT}")


if __name__ == "__main__":
    main()
