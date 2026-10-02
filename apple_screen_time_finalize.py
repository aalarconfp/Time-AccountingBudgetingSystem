# apple_screen_time_finalize.py
"""Finalize a period's canonical Apple Screen Time source layer.

Two steps, both local and $0:

``--promote``
    Copy validated Opal reconstruction estimates (see
    opal_screen_time_reconstruction.py) into the canonical iPhone
    Fact_Time / Daily_Time layer, one file set per estimated date:

        output/Fact/Time/AppleScreenTime/iPhone/Fact_Time_<date>.csv
        output/Daily/Time/AppleScreenTime/iPhone/Daily_Time_<date>.csv
        output/Daily/Time/AppleScreenTime/iPhone/Daily_Time_<date>.metadata.json

    Rows keep the existing Daily_Time schema; estimated provenance is carried
    by Allocation_Type=Estimated, Evidence_Type and Evidence_Source, with the
    remaining reconstruction provenance in the metadata file
    (evidence_class=ESTIMATED). No Raw extraction or app-level rows are
    created. Existing canonical files are never overwritten.

``--validate`` (always runs)
    Check every date of the period: one Fact and one Daily file per date,
    no duplicates, no foreign dates or sources, estimated and observed days
    never mixed, Fact == Daily, observed Daily == Apple headline, estimated
    Daily == reconstruction estimate. Writes a source reconciliation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
FACT_DIR = PROJECT_ROOT / "output" / "Fact" / "Time" / "AppleScreenTime" / "iPhone"
DAILY_DIR = PROJECT_ROOT / "output" / "Daily" / "Time" / "AppleScreenTime" / "iPhone"
RECONSTRUCTION_ROOT = (
    PROJECT_ROOT / "output" / "Analysis" / "Reconstruction" / "Opal_AppleScreenTime"
)
FINALIZATION_ROOT = PROJECT_ROOT / "output" / "Analysis" / "AppleScreenTime" / "Finalization"

FACT_COLUMNS = [
    "Date", "Source", "Category", "Subcategory", "App", "Duration_sec",
    "Event_Count", "Allocation_Type", "Evidence_Type", "Evidence_Source",
]
DAILY_COLUMNS = [
    "Date", "Source", "Category", "Subcategory", "Duration_sec", "Event_Count",
    "Allocation_Type", "Evidence_Type", "Evidence_Source",
]
SOURCE = "iphone"
ESTIMATED = "Estimated"
OBSERVED_ALLOCATION_TYPES = {"Observed", "Derived", "Mixed"}
ESTIMATED_EVIDENCE_TYPE = "Opal_Calibrated_Estimate"
RESIDUAL_SUBCATEGORY = "Screen Time / System"
# An observed day whose headline is mostly unattributed residual is REVIEW.
UNRESOLVED_SHARE_REVIEW = 0.5
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class FinalizeError(Exception):
    """Raised for unsafe or inconsistent finalization input."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inclusive_dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def rel(path: Path) -> str:
    """Project-relative path when possible (forward slashes)."""
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    lines = [",".join(columns)]
    for row in rows:
        values = []
        for column in columns:
            value = str(row.get(column, ""))
            if any(ch in value for ch in ',"\n'):
                value = '"' + value.replace('"', '""') + '"'
            values.append(value)
        lines.append(",".join(values))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

def verify_reconstruction(recon_dir: Path) -> dict[str, Any]:
    """The reconstruction outputs must be unchanged since their audit trail."""
    audit_path = recon_dir / "14_Audit_Trail.json"
    if not audit_path.exists():
        raise FinalizeError(f"Reconstruction audit trail not found: {audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    for name, expected in audit["outputs_sha256"].items():
        actual = sha256_file(recon_dir / name)
        if actual != expected:
            raise FinalizeError(f"Reconstruction output changed since audit: {name}")
    return audit


def build_promotion(recon_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {date: {"rows": [...], "record": {...}}} for promotable dates."""
    audit = verify_reconstruction(recon_dir)
    records = {r["Date"]: r for r in read_csv(recon_dir / "04_Reconstructed_Daily_Totals.csv")}
    allocation = read_csv(recon_dir / "05_Reconstructed_Category_Allocation.csv")

    plan: dict[str, dict[str, Any]] = {}
    for day, record in sorted(records.items()):
        if record["Estimate_Status"] != "ESTIMATED":
            raise FinalizeError(f"{day}: not estimated ({record['Estimate_Status']}); resolve first")
        if record["Review_Status"] != "READY":
            raise FinalizeError(f"{day}: reconstruction is REVIEW ({record['Review_Reasons']})")
        rows = [r for r in allocation if r["Date"] == day]
        total = sum(int(r["Duration_sec"]) for r in rows)
        if total != int(record["Estimated_Apple_Seconds"]):
            raise FinalizeError(f"{day}: allocation does not reconcile to the estimated total")
        for r in rows:
            if r["Allocation_Type"] != ESTIMATED or r["Evidence_Type"] != ESTIMATED_EVIDENCE_TYPE:
                raise FinalizeError(f"{day}: allocation row is not marked as an estimate")
        plan[day] = {"rows": rows, "record": record, "audit": audit}
    return plan


def promotion_files(day: str, rows: list[dict[str, str]], record: dict[str, str],
                    recon_dir: Path) -> dict[str, str]:
    """Text of the Fact, Daily and metadata files for one estimated date."""
    kept = [r for r in rows if int(r["Duration_sec"]) > 0]  # mirror observed: no zero rows
    fact_rows = [{**{k: r[k] for k in DAILY_COLUMNS}, "App": ""} for r in kept]
    daily_rows = [{k: r[k] for k in DAILY_COLUMNS} for r in kept]
    total = sum(int(r["Duration_sec"]) for r in kept)
    first = rows[0]
    metadata = {
        "date": day,
        "source": SOURCE,
        "evidence_class": "ESTIMATED",
        "builder": "apple_screen_time_finalize.py",
        "api_calls": 0,
        "estimated_cost_usd": 0.0,
        "provenance": {
            "allocation_type": ESTIMATED,
            "evidence_type": first["Evidence_Type"],
            "evidence_source": first["Evidence_Source"],
            "source_detail": first["Source_Detail"],
            "estimation_method": first["Estimation_Method"],
            "category_allocation": first["Category_Allocation"],
            "category_model": first["Category_Model"],
            "category_history": first["Category_History"],
            "current_period_validation": first["Current_Period_Validation"],
            "calibration_version": first["Calibration_Version"],
            "opal_report_id": record["Opal_Report_ID"],
            "opal_source_screenshot": record["Opal_Source_Screenshot"],
            "opal_minutes": int(record["Opal_Minutes"]),
            "calibration_minutes": float(record["Calibration_Minutes"]),
            "estimated_apple_minutes": int(record["Estimated_Apple_Minutes"]),
        },
        "reconstruction": {
            "directory": rel(recon_dir),
            "daily_totals_sha256": sha256_file(recon_dir / "04_Reconstructed_Daily_Totals.csv"),
            "category_allocation_sha256": sha256_file(recon_dir / "05_Reconstructed_Category_Allocation.csv"),
        },
        "fact": {"rows": len(fact_rows), "duration_sec": total},
        "daily": {"rows": len(daily_rows), "duration_sec": total},
    }
    return {
        "fact": csv_text(FACT_COLUMNS, fact_rows),
        "daily": csv_text(DAILY_COLUMNS, daily_rows),
        "metadata": json.dumps(metadata, indent=2) + "\n",
    }


def promote(recon_dir: Path, fact_dir: Path, daily_dir: Path) -> list[dict[str, Any]]:
    """Write estimated canonical files; never overwrite different content."""
    plan = build_promotion(recon_dir)
    staged = []
    for day, item in plan.items():
        texts = promotion_files(day, item["rows"], item["record"], recon_dir)
        targets = {
            "fact": fact_dir / f"Fact_Time_{day}.csv",
            "daily": daily_dir / f"Daily_Time_{day}.csv",
            "metadata": daily_dir / f"Daily_Time_{day}.metadata.json",
        }
        status = "NEW"
        existing = [k for k, p in targets.items() if p.exists()]
        if existing:
            if all(targets[k].exists() and targets[k].read_text(encoding="utf-8") == texts[k]
                   for k in targets):
                status = "UNCHANGED"
            else:
                raise FinalizeError(
                    f"{day}: canonical Apple file(s) already exist with different content "
                    f"({', '.join(existing)}); refusing to overwrite"
                )
        staged.append((day, targets, texts, status))

    # All checks passed for every date before anything is written.
    receipts = []
    for day, targets, texts, status in staged:
        if status == "NEW":
            for kind, path in targets.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(texts[kind])
        receipts.append({
            "date": day,
            "status": status,
            "files": {k: rel(p) for k, p in targets.items()},
            "sha256": {k: hashlib.sha256(texts[k].encode("utf-8")).hexdigest() for k in texts},
        })
    return receipts


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_day(day: date, fact_dir: Path, daily_dir: Path,
                 recon_records: dict[str, dict[str, str]]) -> dict[str, Any]:
    iso = day.isoformat()
    fact_path = fact_dir / f"Fact_Time_{iso}.csv"
    daily_path = daily_dir / f"Daily_Time_{iso}.csv"
    meta_path = daily_dir / f"Daily_Time_{iso}.metadata.json"
    issues: list[str] = []
    review: list[str] = []
    row = {
        "Date": iso, "Weekday": WEEKDAYS[day.weekday()], "Apple_Status": "MISSING",
        "Source": "", "Observed_Headline_Min": "", "Observed_Daily_Min": "",
        "Visible_Category_Min": "", "Unresolved_Residual_Min": "", "Estimated_Min": "",
        "Category_Status": "", "Provenance": "", "Daily_Rows": 0, "Review_Status": "",
        "Review_Reasons": "",
    }
    if not daily_path.exists() or not fact_path.exists() or not meta_path.exists():
        missing = [p.name for p in (fact_path, daily_path, meta_path) if not p.exists()]
        row.update(Review_Status="FAIL", Review_Reasons="Missing " + ", ".join(missing))
        return row

    daily = read_csv(daily_path)
    fact = read_csv(fact_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    row["Daily_Rows"] = len(daily)

    for r in daily + fact:
        if r["Date"] != iso:
            issues.append(f"foreign date {r['Date']}")
        if r["Source"] != SOURCE:
            issues.append(f"foreign source {r['Source']}")
    keys = [(r["Category"], r["Subcategory"]) for r in daily]
    if len(keys) != len(set(keys)):
        issues.append("duplicate Category/Subcategory rows")
    daily_total = sum(int(r["Duration_sec"]) for r in daily)
    fact_total = sum(int(r["Duration_sec"]) for r in fact)
    if daily_total != fact_total:
        issues.append(f"Fact {fact_total}s != Daily {daily_total}s")

    types = {r["Allocation_Type"] for r in daily + fact}
    if metadata.get("evidence_class") == "ESTIMATED":
        row["Apple_Status"] = "ESTIMATED"
        prov = metadata.get("provenance", {})
        row["Source"] = f"Opal ({prov.get('opal_report_id', '')})"
        row["Estimated_Min"] = daily_total / 60
        row["Category_Status"] = f"Estimated — {prov.get('category_model', '')}"
        row["Provenance"] = (
            f"Allocation_Type=Estimated; Evidence_Type={prov.get('evidence_type')}; "
            f"Category_Allocation={prov.get('category_allocation')}"
        )
        if types != {ESTIMATED}:
            issues.append(f"estimated day contains non-estimated rows {sorted(types - {ESTIMATED})}")
        if any(r["Evidence_Type"] != ESTIMATED_EVIDENCE_TYPE for r in daily):
            issues.append("estimated row with wrong Evidence_Type")
        record = recon_records.get(iso)
        if record is None:
            issues.append("estimated day not present in the reconstruction output")
        elif int(record["Estimated_Apple_Seconds"]) != daily_total:
            issues.append("Daily total differs from the reconstruction estimate")
    else:
        row["Apple_Status"] = "OBSERVED"
        row["Source"] = "Apple Screen Time screenshots"
        if not types <= OBSERVED_ALLOCATION_TYPES:
            issues.append(f"observed day contains non-observed rows {sorted(types - OBSERVED_ALLOCATION_TYPES)}")
        headline = (metadata.get("reconciliation") or {}).get("headline_seconds")
        residual = sum(int(r["Duration_sec"]) for r in daily if r["Subcategory"] == RESIDUAL_SUBCATEGORY
                       and r["Allocation_Type"] == "Derived")
        row.update(
            Observed_Headline_Min=headline / 60 if headline is not None else "",
            Observed_Daily_Min=daily_total / 60,
            Visible_Category_Min=(daily_total - residual) / 60,
            Unresolved_Residual_Min=residual / 60,
            Provenance="Allocation_Type=Observed/Derived/Mixed; Evidence_Type=Apple Screen Time",
        )
        status = (metadata.get("reconciliation") or {}).get("status", "")
        if headline is None:
            issues.append("observed day has no Apple headline in metadata")
        elif daily_total != headline and status != "VISIBLE_CATEGORIES_EXCEED_HEADLINE":
            issues.append(f"Daily {daily_total}s does not reconcile to headline {headline}s")
        if headline and residual / headline > UNRESOLVED_SHARE_REVIEW:
            review.append(
                f"{residual / headline:.0%} of the Apple headline is unattributed residual "
                f"(Utilities / {RESIDUAL_SUBCATEGORY}, Derived); category evidence incomplete"
            )
        row["Category_Status"] = (
            "Observed — incomplete (residual majority)" if review else
            f"Observed — reconciled to headline ({status})"
        )

    row["Review_Status"] = "FAIL" if issues else ("REVIEW" if review else "PASS")
    row["Review_Reasons"] = "; ".join(issues + review)
    return row


def validate_period(start: date, end: date, fact_dir: Path, daily_dir: Path,
                    recon_dir: Path | None) -> dict[str, Any]:
    recon_records = {}
    if recon_dir is not None and (recon_dir / "04_Reconstructed_Daily_Totals.csv").exists():
        recon_records = {r["Date"]: r for r in read_csv(recon_dir / "04_Reconstructed_Daily_Totals.csv")}
    rows = [validate_day(d, fact_dir, daily_dir, recon_records) for d in inclusive_dates(start, end)]
    estimated = [r for r in rows if r["Apple_Status"] == "ESTIMATED"]
    observed = [r for r in rows if r["Apple_Status"] == "OBSERVED"]
    return {
        "rows": rows,
        "dates": len(rows),
        "estimated_days": len(estimated),
        "observed_days": len(observed),
        "missing_days": [r["Date"] for r in rows if r["Apple_Status"] == "MISSING"],
        "fail_days": [r["Date"] for r in rows if r["Review_Status"] == "FAIL"],
        "review_days": [r["Date"] for r in rows if r["Review_Status"] == "REVIEW"],
        "estimated_minutes": sum(r["Estimated_Min"] for r in estimated),
        "observed_minutes": sum(r["Observed_Daily_Min"] for r in observed),
    }


def write_reports(out_dir: Path, result: dict[str, Any], receipts: list[dict[str, Any]] | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = list(result["rows"][0].keys())
    formatted = [
        {k: (f"{v:.2f}" if isinstance(v, float) else v) for k, v in r.items()} for r in result["rows"]
    ]
    (out_dir / "Apple_Source_Reconciliation.csv").write_text(csv_text(columns, formatted), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "rows"}
    (out_dir / "Apple_Finalization_Summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if receipts is not None:
        (out_dir / "Apple_Estimate_Promotion_Receipt.json").write_text(
            json.dumps(receipts, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--reconstruction-dir", type=Path, default=None,
                        help="Validated Opal reconstruction directory (required with --promote).")
    parser.add_argument("--promote", action="store_true",
                        help="Promote reconstruction estimates into the canonical layer first.")
    args = parser.parse_args(argv)
    start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    try:
        receipts = None
        if args.promote:
            if args.reconstruction_dir is None:
                raise FinalizeError("--promote requires --reconstruction-dir")
            receipts = promote(args.reconstruction_dir, FACT_DIR, DAILY_DIR)
            for r in receipts:
                print(f"{r['date']} | {r['status']} | estimated canonical Fact/Daily/metadata")
        result = validate_period(start, end, FACT_DIR, DAILY_DIR, args.reconstruction_dir)
    except FinalizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_dir = FINALIZATION_ROOT / f"{start.isoformat()}_{end.isoformat()}"
    write_reports(out_dir, result, receipts)
    for r in result["rows"]:
        print(f"{r['Date']} | {r['Apple_Status']:<9} | {r['Review_Status']:<6} | "
              f"{(r['Estimated_Min'] or r['Observed_Daily_Min'] or 0):>7.1f} min | {r['Review_Reasons']}")
    print(f"Dates {result['dates']} | estimated {result['estimated_days']} | observed {result['observed_days']}"
          f" | missing {len(result['missing_days'])} | FAIL {len(result['fail_days'])}"
          f" | REVIEW {len(result['review_days'])}")
    print(f"Estimated {result['estimated_minutes']:.1f} min | observed {result['observed_minutes']:.1f} min"
          f" | total {result['estimated_minutes'] + result['observed_minutes']:.1f} min")
    print(f"Report: {out_dir}")
    if result["missing_days"] or result["fail_days"]:
        print("RESULT: APPLE SOURCE LAYER VALIDATION FAILED.")
        return 1
    if result["review_days"]:
        print("RESULT: APPLE SOURCE LAYER COMPLETE — REVIEW ITEMS REMAIN.")
        return 0
    print("RESULT: APPLE SOURCE LAYER VALIDATION PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
