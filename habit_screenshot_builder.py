# habit_screenshot_builder.py
"""Build canonical Habit / Off-Device Daily_Time from normalized evidence.

Consumes the output of habit_screenshot_ingest.py. One row is written per
Habit category per date (the layout habit_manual_adjustments.py relies on):

- evidence row present      -> its duration and provenance
- no evidence, but a monthly screenshot covers the tracker
                            -> 0 min, Observed, "Monthly Calendar"
                               (the calendar shows the day was not completed)
- no evidence at all        -> 0 min, Review, "No Evidence"

No cumulative state, baselines or previous snapshots are read.

Outputs (per date):
    <root>/Daily/Time/Habit/OffDevice/Daily_Time_<date>.csv
    <root>/Daily/Time/Habit/OffDevice/Daily_Time_<date>.metadata.json
    <root>/Fact/Time/Habit/OffDevice/Fact_Time_<date>.csv
Audit (per month):
    <root>/Analysis/Habit/Screenshot/<month>/Habit_Audit_*.csv|json|md
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import habit_screenshot_ingest as ingest

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
SOURCE = "habit_offdevice"
DAILY_COLUMNS = [
    "Date", "Source", "Category", "Subcategory", "Duration_sec", "Event_Count",
    "Allocation_Type", "Evidence_Type", "Evidence_Source",
]
NO_EVIDENCE = "No Evidence"
DATE_MAPPING_REVIEW = "date mapping REVIEW"


def unresolved_date_mappings(days: dict[str, list[dict[str, Any]]]) -> list[str]:
    return [f"{r['Date']} {r['Category']}" for rows in days.values() for r in rows
            if DATE_MAPPING_REVIEW in r["Evidence_Type"]]


class BuildError(Exception):
    """Unsafe or inconsistent build request."""


def read_normalized(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise BuildError(f"Normalized evidence not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def evidence_source(row: dict[str, str], month: str) -> str:
    files = [row["Evidence_File"]] + [f for f in row.get("Supporting_Files", "").split(";") if f]
    source = "; ".join(f"input/Habit/{month}/{f}" for f in files)
    if row.get("Calibration_Reference"):
        source += f" | {row['Calibration_Reference']}"
    return source


def build_month(month: str, normalized_path: Path, coverage: dict[str, list[str]]) -> dict[str, list[dict[str, Any]]]:
    """Return {date: daily rows} for every date of the month."""
    rows = read_normalized(normalized_path)
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["Date"], row["Category"])
        if key in by_key:
            raise BuildError(f"Duplicate normalized evidence for {key}")
        if row["Category"] not in ingest.HABIT_CATEGORIES:
            raise BuildError(f"Unknown category {row['Category']!r}")
        by_key[key] = row

    days: dict[str, list[dict[str, Any]]] = {}
    for day in ingest.month_dates(month):
        iso = day.isoformat()
        daily = []
        for category in ingest.HABIT_CATEGORIES:
            row = by_key.get((iso, category))
            if row is not None:
                seconds = int(row["Duration_sec"])
                evidence_type = row["Evidence_Type"]
                if row.get("Date_Mapping_Status", "CONFIRMED") != "CONFIRMED":
                    evidence_type += f" ({DATE_MAPPING_REVIEW})"
                daily.append({
                    "Date": iso, "Source": SOURCE, "Category": category, "Subcategory": category,
                    "Duration_sec": seconds,
                    "Event_Count": 1 if (seconds > 0 or row["Completed"] == "TRUE") else 0,
                    "Allocation_Type": row["Allocation_Type"],
                    "Evidence_Type": evidence_type,
                    "Evidence_Source": evidence_source(row, month),
                })
            elif coverage.get(category):
                daily.append({
                    "Date": iso, "Source": SOURCE, "Category": category, "Subcategory": category,
                    "Duration_sec": 0, "Event_Count": 0, "Allocation_Type": ingest.OBSERVED,
                    "Evidence_Type": ingest.EVIDENCE_MONTHLY_CALENDAR,
                    "Evidence_Source": "; ".join(f"input/Habit/{month}/{f}" for f in coverage[category])
                                       + " | not completed",
                })
            else:
                daily.append({
                    "Date": iso, "Source": SOURCE, "Category": category, "Subcategory": category,
                    "Duration_sec": 0, "Event_Count": 0, "Allocation_Type": ingest.REVIEW,
                    "Evidence_Type": NO_EVIDENCE, "Evidence_Source": "",
                })
        days[iso] = daily
    unused = {k for k in by_key if k[0] not in days}
    if unused:
        raise BuildError(f"Evidence outside {month}: {sorted(unused)}")
    return days


def csv_text(rows: list[dict[str, Any]]) -> str:
    def cell(value: Any) -> str:
        text = str(value)
        return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text
    lines = [",".join(DAILY_COLUMNS)] + [",".join(cell(r[c]) for c in DAILY_COLUMNS) for r in rows]
    return "\n".join(lines) + "\n"


def write_month(month: str, days: dict[str, list[dict[str, Any]]], root: Path,
                normalized_path: Path, force: bool) -> list[dict[str, str]]:
    daily_dir = root / "Daily" / "Time" / "Habit" / "OffDevice"
    fact_dir = root / "Fact" / "Time" / "Habit" / "OffDevice"
    plan = []
    for iso, rows in days.items():
        text = csv_text(rows)
        meta = {
            "date": iso, "source": SOURCE, "builder": "habit_screenshot_builder.py",
            "model": "direct screenshot evidence (no cumulative deltas)",
            "normalized_evidence": normalized_path.name,
            "duration_sec": sum(r["Duration_sec"] for r in rows),
            "allocation_types": sorted({r["Allocation_Type"] for r in rows}),
            "api_calls": 0,
        }
        targets = {
            daily_dir / f"Daily_Time_{iso}.csv": text,
            fact_dir / f"Fact_Time_{iso}.csv": text,
            daily_dir / f"Daily_Time_{iso}.metadata.json": json.dumps(meta, indent=2) + "\n",
        }
        existing = [p for p, t in targets.items() if p.exists() and p.read_text(encoding="utf-8") != t]
        if existing and not force:
            raise BuildError(f"{iso}: Habit output already exists with different content "
                             f"({existing[0].name}); use --force to replace")
        plan.append((iso, targets))
    receipts = []
    for iso, targets in plan:
        for path, text in targets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        receipts.append({"date": iso, "files": [str(p) for p in targets]})
    return receipts


def audit(month: str, days: dict[str, list[dict[str, Any]]], bar_meta: dict[str, Any],
          out_dir: Path) -> dict[str, Any]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    days_used: dict[str, int] = defaultdict(int)
    review = []
    for rows in days.values():
        for r in rows:
            totals[r["Category"]][r["Allocation_Type"]] += r["Duration_sec"] / 60
            if r["Duration_sec"] > 0 or r["Event_Count"]:
                days_used[r["Category"]] += 1
            if r["Allocation_Type"] == ingest.REVIEW or DATE_MAPPING_REVIEW in r["Evidence_Type"]:
                review.append(f"{r['Date']} {r['Category']}: {r['Allocation_Type']} / {r['Evidence_Type']}")
    summary_rows = []
    for category in ingest.HABIT_CATEGORIES:
        by_type = totals[category]
        summary_rows.append({
            "Category": category,
            "Days_With_Evidence": days_used[category],
            "Total_Min": round(sum(by_type.values()), 2),
            "Observed_Min": round(by_type.get(ingest.OBSERVED, 0), 2),
            "Target_Derived_Min": round(by_type.get(ingest.TARGET_DERIVED, 0), 2),
            "Inferred_Min": round(by_type.get(ingest.INFERRED, 0), 2),
            "Review_Min": round(by_type.get(ingest.REVIEW, 0), 2),
            "Mean_Daily_Min": round(sum(by_type.values()) / len(days), 2),
        })
    out_dir.mkdir(parents=True, exist_ok=True)
    ingest.write_csv(out_dir / f"Habit_Audit_Category_Totals_{month}.csv",
                     list(summary_rows[0].keys()), summary_rows)
    all_rows = [r for rows in days.values() for r in rows]
    ingest.write_csv(out_dir / f"Habit_Audit_Daily_Rows_{month}.csv", DAILY_COLUMNS, all_rows)
    result = {"month": month, "dates": len(days), "category_totals": summary_rows,
              "review_items": review, "bar_charts": bar_meta.get("bar_charts", [])}
    (out_dir / f"Habit_Audit_Summary_{month}.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [f"# Habit / Off-Device audit — {month}", "",
             "| Category | Days | Total min | Observed | Target-derived | Inferred | Review |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in summary_rows:
        lines.append(f"| {r['Category']} | {r['Days_With_Evidence']} | {r['Total_Min']:g} | "
                     f"{r['Observed_Min']:g} | {r['Target_Derived_Min']:g} | {r['Inferred_Min']:g} | "
                     f"{r['Review_Min']:g} |")
    for chart in result["bar_charts"]:
        lines.append(f"\n{chart['category']} ({chart['evidence_file']}): calibrated mean "
                     f"{chart['calibrated_mean_min']:.2f} min vs displayed {chart['reference_average_min']:.0f} min; "
                     f"factor {chart['calibration_factor']:.4f}. {chart.get('notes', '')}")
    for chart in result["bar_charts"]:
        if chart.get("date_alignment_status") != "CONFIRMED":
            lines.append(f"\n{chart['category']} date alignment: {chart.get('date_alignment_status')} - "
                         f"{chart.get('date_alignment_notes', '')}")
        if chart.get("bars_outside_month"):
            lines.append(f"{chart['category']} bars outside the month (excluded): {chart['bars_outside_month']}")
        if chart.get("cross_check"):
            cc = chart["cross_check"]
            lines.append(f"{chart['evidence_file']} cross-check vs {cc['against']}: {len(cc['dates'])} dates, "
                         f"mean |diff| {cc['mean_abs_diff_min']:.1f} min, max {cc['max_abs_diff_min']} min "
                         f"(tolerance {cc['tolerance_min']})")
        if chart.get("category_dates_without_value"):
            lines.append(f"{chart['category']} dates without a value: {chart['category_dates_without_value']}")
    lines.append(f"\nREVIEW items: {len(review)}")
    lines += [f"- {item}" for item in review]
    (out_dir / f"Habit_Audit_Report_{month}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical Habit Daily_Time from normalized evidence.")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--normalized-dir", type=Path, default=None,
                        help="Folder with Habit_Evidence_Normalized_<month>.csv "
                             "(default output/Raw/Habit/<month>).")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT,
                        help="Root for Daily/Fact/Analysis (default output/; use a scratch folder to stage).")
    parser.add_argument("--force", action="store_true", help="Replace existing Habit outputs for the month.")
    parser.add_argument("--allow-unresolved-mapping", action="store_true",
                        help="Permit a canonical write while a bar-chart date mapping is REVIEW "
                             "(never needed for staging).")
    args = parser.parse_args(argv)
    normalized_dir = args.normalized_dir or ingest.NORMALIZED_ROOT / args.month
    normalized_path = normalized_dir / f"Habit_Evidence_Normalized_{args.month}.csv"
    meta_path = normalized_dir / f"Habit_Evidence_Normalized_{args.month}.json"
    try:
        if not meta_path.exists():
            raise BuildError(f"Normalized evidence metadata not found: {meta_path}")
        bar_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        days = build_month(args.month, normalized_path, bar_meta["calendar_coverage"])
        unresolved = unresolved_date_mappings(days)
        canonical = args.output_root.resolve() == OUTPUT_ROOT.resolve()
        if unresolved and canonical and not args.allow_unresolved_mapping:
            raise BuildError(
                f"{len(unresolved)} rows have an unresolved bar-chart date mapping "
                f"(e.g. {unresolved[0]}); resolve it before a canonical write, or stage with --output-root"
            )
        write_month(args.month, days, args.output_root, normalized_path, args.force)
        result = audit(args.month, days, bar_meta,
                       args.output_root / "Analysis" / "Habit" / "Screenshot" / args.month)
    except (BuildError, ingest.EvidenceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Habit {args.month}: {result['dates']} dates built under {args.output_root}")
    for r in result["category_totals"]:
        print(f"  {r['Category']:<24} {r['Total_Min']:>8g} min  (obs {r['Observed_Min']:g}, "
              f"target {r['Target_Derived_Min']:g}, inferred {r['Inferred_Min']:g})")
    print(f"REVIEW items: {len(result['review_items'])}")
    print("RESULT: HABIT DAILY_TIME BUILT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
