# habit_screenshot_ingest.py
"""Habit / Off-Device evidence discovery, normalization and validation.

Screenshots are treated as direct evidence for daily Habit values. There are
no cumulative weekly/monthly deltas, no resets, no baselines and no previous
snapshots.

Evidence for one month lives in ``input/Habit/<YYYY-MM>/``:

    *.PNG / *.JPG                       original screenshots (never modified)
    Habit_Screenshot_Index_<M>.csv      every image classified by tracker/role
    Habit_Evidence_Manifest_<M>.csv     daily evidence rows (human-curated)
    Habit_Bar_Charts_<M>.json           bar-chart measurement configuration

Evidence classes (Allocation_Type / Evidence_Type):

    OBSERVED        Observed        Monthly Calendar | Daily Screenshot
    TARGET_DERIVED  Target_Derived  Target Duration (configured target only)
    INFERRED        Inferred        Monthly / Weekly Bar Estimate (bar height,
                                    calibrated to the displayed average)
    COMPLETED_ONLY  Review          Completed Without Duration (0 min, flagged)

Output: one normalized evidence CSV consumed by habit_screenshot_builder.py.
No API calls are made; the manifest is deterministic.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_ROOT = PROJECT_ROOT / "input" / "Habit"
NORMALIZED_ROOT = PROJECT_ROOT / "output" / "Raw" / "Habit"

HABIT_CATEGORIES: tuple[str, ...] = (
    "Workout",
    "Read a book",
    "Meditation",
    "Offline Study Tracker",
    "Offline Work Tracking",
    "Family Time Tracking",
    "Social Time Tracking",
    "TV Time tracking",
    "Personal Time Tracking",
    "Journaling",
    "Sleep",
    "Motorcycle Time",
    "Console Time Tracking",
)

# Configured targets: used only for TARGET_DERIVED evidence.
TARGET_MINUTES: dict[str, int] = {
    "Journaling": 15,
    "Meditation": 15,
    "Read a book": 30,
    "Motorcycle Time": 120,
}

OBSERVED = "Observed"
TARGET_DERIVED = "Target_Derived"
INFERRED = "Inferred"
REVIEW = "Review"

EVIDENCE_MONTHLY_CALENDAR = "Monthly Calendar"
EVIDENCE_DAILY_SCREENSHOT = "Daily Screenshot"
EVIDENCE_BAR_ESTIMATE = "Monthly Bar Estimate"
EVIDENCE_WEEKLY_BAR_ESTIMATE = "Weekly Bar Estimate"
EVIDENCE_TARGET = "Target Duration"
EVIDENCE_COMPLETED_ONLY = "Completed Without Duration"

# Allowed (Allocation_Type, Evidence_Type) pairs in the manifest.
MANIFEST_RULES: dict[tuple[str, str], str] = {
    (OBSERVED, EVIDENCE_MONTHLY_CALENDAR): "duration_required",
    (OBSERVED, EVIDENCE_DAILY_SCREENSHOT): "duration_required",
    (TARGET_DERIVED, EVIDENCE_TARGET): "target",
    (REVIEW, EVIDENCE_COMPLETED_ONLY): "no_duration",
}

INDEX_ROLES = {"MONTHLY_CALENDAR", "DAILY_DETAIL", "MONTHLY_BAR", "WEEKLY_BAR", "DUPLICATE"}
BAR_ROLES = {"MONTHLY_BAR", "WEEKLY_BAR"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

INDEX_COLUMNS = ("Evidence_File", "Category", "Role", "Evidence_Date",
                 "Covers_Month", "Duplicate_Of", "Notes")
MANIFEST_COLUMNS = ("Date", "Category", "Completed", "Duration_min", "Evidence_Type",
                    "Allocation_Type", "Evidence_File", "Notes")
NORMALIZED_COLUMNS = [
    "Date", "Category", "Completed", "Duration_min", "Duration_sec", "Evidence_Type",
    "Allocation_Type", "Evidence_File", "Supporting_Files", "Calibration_Reference",
    "Date_Mapping_Status", "Notes",
]
DATE_MAPPING_STATUSES = {"CONFIRMED", "REVIEW"}


class EvidenceError(Exception):
    """Invalid or inconsistent Habit evidence."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def month_dates(month: str) -> list[date]:
    year, mon = (int(p) for p in month.split("-"))
    first = date(year, mon, 1)
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists():
        raise EvidenceError(f"Missing evidence file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise EvidenceError(f"{path.name} is missing columns {sorted(missing)}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


# ---------------------------------------------------------------------------
# 1. Discovery: screenshot index
# ---------------------------------------------------------------------------

@dataclass
class ScreenshotIndex:
    entries: dict[str, dict[str, str]]
    calendar_coverage: dict[str, list[str]]  # category -> files covering the month

    def primary(self, name: str) -> str:
        entry = self.entries[name]
        return entry["Duplicate_Of"] or name


def load_index(month_dir: Path, month: str) -> ScreenshotIndex:
    """Every image in the month folder must be classified exactly once."""
    rows = read_csv(month_dir / f"Habit_Screenshot_Index_{month}.csv", INDEX_COLUMNS)
    entries: dict[str, dict[str, str]] = {}
    for row in rows:
        name = row["Evidence_File"]
        if name in entries:
            raise EvidenceError(f"Screenshot indexed twice: {name}")
        if row["Category"] not in HABIT_CATEGORIES:
            raise EvidenceError(f"{name}: unknown category {row['Category']!r}")
        if row["Role"] not in INDEX_ROLES:
            raise EvidenceError(f"{name}: unknown role {row['Role']!r}")
        if not (month_dir / name).exists():
            raise EvidenceError(f"Indexed screenshot not found: {name}")
        entries[name] = row
    for name, row in entries.items():
        if row["Role"] == "DUPLICATE":
            target = entries.get(row["Duplicate_Of"])
            if target is None or target["Category"] != row["Category"]:
                raise EvidenceError(f"{name}: invalid Duplicate_Of {row['Duplicate_Of']!r}")
        elif row["Duplicate_Of"]:
            raise EvidenceError(f"{name}: Duplicate_Of set on a non-duplicate role")

    on_disk = sorted(p.name for p in month_dir.iterdir()
                     if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    unindexed = [n for n in on_disk if n not in entries]
    if unindexed:
        raise EvidenceError(f"Screenshots not classified in the index: {unindexed}")

    coverage: dict[str, list[str]] = {}
    for name, row in entries.items():
        # Only calendars show "not completed"; a bar chart never implies a zero day.
        if row["Covers_Month"].upper() == "TRUE" and row["Role"] in ("MONTHLY_CALENDAR", "DAILY_DETAIL"):
            coverage.setdefault(row["Category"], []).append(name)
    return ScreenshotIndex(entries, coverage)


# ---------------------------------------------------------------------------
# 2a. Manifest normalization
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRow:
    date: date
    category: str
    completed: bool
    duration_min: float
    evidence_type: str
    allocation_type: str
    evidence_file: str
    supporting_files: list[str] = field(default_factory=list)
    calibration_reference: str = ""
    date_mapping_status: str = "CONFIRMED"
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "Date": self.date.isoformat(),
            "Category": self.category,
            "Completed": "TRUE" if self.completed else "FALSE",
            "Duration_min": f"{self.duration_min:g}",
            "Duration_sec": round_half_up(self.duration_min * 60),
            "Evidence_Type": self.evidence_type,
            "Allocation_Type": self.allocation_type,
            "Evidence_File": self.evidence_file,
            "Supporting_Files": ";".join(self.supporting_files),
            "Calibration_Reference": self.calibration_reference,
            "Date_Mapping_Status": self.date_mapping_status,
            "Notes": self.notes,
        }


def normalize_manifest_row(row: dict[str, str], month: str, index: ScreenshotIndex) -> EvidenceRow:
    where = f"manifest {row['Date']} / {row['Category']}"
    try:
        day = date.fromisoformat(row["Date"])
    except ValueError as exc:
        raise EvidenceError(f"{where}: invalid date") from exc
    if day.strftime("%Y-%m") != month:
        raise EvidenceError(f"{where}: date outside {month}")
    category = row["Category"]
    if category not in HABIT_CATEGORIES:
        raise EvidenceError(f"{where}: unknown category")
    key = (row["Allocation_Type"], row["Evidence_Type"])
    rule = MANIFEST_RULES.get(key)
    if rule is None:
        raise EvidenceError(f"{where}: Allocation_Type/Evidence_Type {key} not allowed in the manifest")
    evidence_file = row["Evidence_File"]
    if evidence_file not in index.entries:
        raise EvidenceError(f"{where}: evidence file {evidence_file!r} is not indexed")
    if index.entries[evidence_file]["Category"] != category:
        raise EvidenceError(f"{where}: evidence file {evidence_file} belongs to another tracker")
    if row["Completed"].upper() != "TRUE":
        raise EvidenceError(f"{where}: manifest rows record completed days only")
    raw = row["Duration_min"]

    if rule == "duration_required":
        if not raw:
            raise EvidenceError(f"{where}: Observed evidence needs an explicit duration")
        duration = float(raw)
        if duration <= 0:
            raise EvidenceError(f"{where}: Observed duration must be positive")
    elif rule == "target":
        target = TARGET_MINUTES.get(category)
        if target is None:
            raise EvidenceError(f"{where}: no configured target for {category}")
        if raw and float(raw) != target:
            raise EvidenceError(f"{where}: Target_Derived duration {raw} != configured target {target}")
        duration = float(target)
    else:  # completed without duration
        if raw:
            raise EvidenceError(f"{where}: Completed Without Duration must not carry a duration")
        duration = 0.0

    return EvidenceRow(
        date=day, category=category, completed=True, duration_min=duration,
        evidence_type=row["Evidence_Type"], allocation_type=row["Allocation_Type"],
        evidence_file=index.primary(evidence_file), notes=row["Notes"],
    )


def merge_duplicates(rows: list[EvidenceRow]) -> list[EvidenceRow]:
    """Identical evidence for one (date, category) is kept once (never summed);
    conflicting evidence is an error."""
    merged: dict[tuple[date, str], EvidenceRow] = {}
    for row in rows:
        key = (row.date, row.category)
        existing = merged.get(key)
        if existing is None:
            merged[key] = row
            continue
        same = (existing.duration_min == row.duration_min
                and existing.allocation_type == row.allocation_type
                and existing.evidence_type == row.evidence_type)
        if not same:
            raise EvidenceError(
                f"Conflicting evidence for {row.date} / {row.category}: "
                f"{existing.duration_min:g} min {existing.allocation_type} ({existing.evidence_file}) vs "
                f"{row.duration_min:g} min {row.allocation_type} ({row.evidence_file})"
            )
        if row.evidence_file != existing.evidence_file and row.evidence_file not in existing.supporting_files:
            existing.supporting_files.append(row.evidence_file)
    return [merged[k] for k in sorted(merged, key=lambda k: (k[0], HABIT_CATEGORIES.index(k[1])))]


# ---------------------------------------------------------------------------
# 2b. Bar charts (INFERRED)
# ---------------------------------------------------------------------------

def measure_bar_heights(image_path: Path, chart: dict[str, Any]) -> dict[int, int]:
    """Return {slot index: bar height px} for bars of the configured colour.

    Slots without a detected bar have height 0 (zero-height bar).
    """
    from PIL import Image  # local import: only needed for bar charts

    x0, y0, x1, y1 = chart["region"]
    lo, hi = chart["color_min"], chart["color_max"]
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    pixels = image.load()
    columns: dict[int, list[int]] = {}
    for x in range(max(0, x0), min(width, x1)):
        ys = [y for y in range(max(0, y0), min(height, y1))
              if all(lo[c] <= pixels[x, y][c] <= hi[c] for c in range(3))]
        if ys:
            columns[x] = ys
    groups: list[list[int]] = []
    for x in sorted(columns):
        if groups and x == groups[-1][-1] + 1:
            groups[-1].append(x)
        else:
            groups.append([x])
    heights: dict[int, int] = {}
    for group in groups:
        if len(group) < chart.get("min_bar_width_px", 3):
            continue
        center = (group[0] + group[-1]) / 2
        slot = round_half_up((center - chart["slot_x0"]) / chart["slot_pitch"])
        top = min(min(columns[x]) for x in group)
        if not 0 <= slot < chart["slots"]:
            raise EvidenceError(f"{image_path.name}: bar at x={center} outside the configured slots")
        if slot in heights:
            raise EvidenceError(f"{image_path.name}: two bars mapped to slot {slot}")
        heights[slot] = chart["baseline_y"] - top
    return {slot: heights.get(slot, 0) for slot in range(chart["slots"])}


def allocate_rounded(values: list[float], unit: int, total: int) -> list[int]:
    """Round to multiples of ``unit`` so the result sums exactly to ``total``
    (largest remainder; ties to the earlier date)."""
    if total % unit:
        raise EvidenceError(f"Calibrated total {total} is not a multiple of {unit}")
    units = [v / unit for v in values]
    floors = [math.floor(u) for u in units]
    remaining = total // unit - sum(floors)
    order = sorted(range(len(units)), key=lambda i: (-(units[i] - floors[i]), i))
    for i in order[:remaining]:
        floors[i] += 1
    return [f * unit for f in floors]


def calibrate_bars(heights: list[int], px_per_min: float | None, reference_average_min: int,
                   rounding_min: int) -> tuple[list[int], dict[str, float]]:
    """Scale bar heights so their mean equals the displayed monthly average.

    With an absolute axis (``px_per_min``) the raw minutes are reported so the
    calibration factor can be checked; with a relative chart only the shape is
    used. Zero-height bars stay 0.
    """
    if not heights or sum(heights) <= 0:
        raise EvidenceError("Bar chart has no measurable bars")
    raw = [h / px_per_min for h in heights] if px_per_min else [float(h) for h in heights]
    target_total = reference_average_min * len(heights)
    factor = target_total / sum(raw)
    rounded = allocate_rounded([r * factor for r in raw], rounding_min, target_total)
    stats = {
        "raw_mean_min": (sum(raw) / len(raw)) if px_per_min else float("nan"),
        "calibration_factor": factor,
        "calibrated_mean_min": sum(rounded) / len(rounded),
        "reference_average_min": float(reference_average_min),
    }
    return rounded, stats


def bar_chart_rows(month_dir: Path, month: str, index: ScreenshotIndex,
                   charts: list[dict[str, Any]]) -> tuple[list[EvidenceRow], list[dict[str, Any]]]:
    """Calibrated bar values for every configured chart.

    ``emit_dates`` (optional) limits which in-month dates a chart supplies;
    its other bars are calibration / cross-check only. ``cross_check_against``
    compares a chart's values with another chart's values on shared dates
    (including dates outside the month) and fails beyond the tolerance, so a
    date mapping is re-verified on every run.
    """
    rows, reports = [], []
    computed: dict[str, dict[date, int]] = {}
    for chart in charts:
        name = chart["evidence_file"]
        role = index.entries.get(name, {}).get("Role")
        if role not in BAR_ROLES:
            raise EvidenceError(f"Bar chart {name} must be indexed with role MONTHLY_BAR or WEEKLY_BAR")
        category = chart["category"]
        if index.entries[name]["Category"] != category:
            raise EvidenceError(f"Bar chart {name} is indexed for another tracker")
        alignment = chart.get("date_alignment_status", "")
        if alignment not in DATE_MAPPING_STATUSES:
            raise EvidenceError(f"Bar chart {name}: date_alignment_status must be CONFIRMED or REVIEW")
        first = date.fromisoformat(chart["first_date"])
        heights_by_slot = measure_bar_heights(month_dir / name, chart)
        heights = [heights_by_slot[s] for s in range(chart["slots"])]
        values, stats = calibrate_bars(heights, chart.get("px_per_min"),
                                       chart["reference_average_min"], chart["rounding_min"])
        for expected_zero in chart.get("expected_zero_dates", []):
            slot = (date.fromisoformat(expected_zero) - first).days
            if heights[slot] != 0:
                raise EvidenceError(f"{name}: expected a zero-height bar on {expected_zero}")
        emit = chart.get("emit_dates")
        emit_dates = None if emit is None else {date.fromisoformat(d) for d in emit}
        evidence_type = EVIDENCE_WEEKLY_BAR_ESTIMATE if role == "WEEKLY_BAR" else EVIDENCE_BAR_ESTIMATE
        reference = (f"{name}: displayed average {chart['reference_average_min']} min "
                     f"over {chart['slots']} bars; calibration factor {stats['calibration_factor']:.4f}")
        computed[name] = {}
        emitted, outside = [], []
        for slot, minutes in enumerate(values):
            day = first + timedelta(days=slot)
            computed[name][day] = minutes
            if day.strftime("%Y-%m") != month:
                # Calibrated with the other bars, but belongs to another month.
                outside.append({"slot": slot, "date": day.isoformat(), "minutes": minutes})
                continue
            if emit_dates is not None and day not in emit_dates:
                continue
            emitted.append(day.isoformat())
            rows.append(EvidenceRow(
                date=day, category=category, completed=minutes > 0,
                duration_min=float(minutes), evidence_type=evidence_type,
                allocation_type=INFERRED, evidence_file=name,
                calibration_reference=reference, date_mapping_status=alignment,
                notes=f"bar {slot + 1} of {chart['slots']}, height {heights[slot]} px",
            ))
        reports.append({
            "category": category, "evidence_file": name, "role": role, "slots": chart["slots"],
            "first_date": chart["first_date"], "date_alignment_status": alignment,
            "date_alignment_notes": chart.get("date_alignment_notes", ""),
            "heights_px": heights, "values_min": values, **stats,
            "bars_outside_month": outside, "emitted_dates": emitted,
            "notes": chart.get("notes", ""),
        })

    for chart, report in zip(charts, reports):
        against = chart.get("cross_check_against")
        if not against:
            continue
        if against not in computed:
            raise EvidenceError(f"{chart['evidence_file']}: cross-check chart {against} is not configured")
        shared = sorted(set(computed[chart["evidence_file"]]) & set(computed[against]))
        if not shared:
            raise EvidenceError(f"{chart['evidence_file']}: no dates shared with {against}")
        diffs = [computed[chart["evidence_file"]][d] - computed[against][d] for d in shared]
        tolerance = chart.get("cross_check_tolerance_min", 10)
        report["cross_check"] = {
            "against": against, "dates": [d.isoformat() for d in shared],
            "mean_abs_diff_min": sum(abs(x) for x in diffs) / len(diffs),
            "max_abs_diff_min": max(abs(x) for x in diffs), "tolerance_min": tolerance,
        }
        if report["cross_check"]["max_abs_diff_min"] > tolerance:
            raise EvidenceError(
                f"{chart['evidence_file']} disagrees with {against} by up to "
                f"{report['cross_check']['max_abs_diff_min']} min on shared dates; date mapping not supported"
            )

    by_category: dict[str, set[date]] = {}
    for row in rows:
        by_category.setdefault(row.category, set()).add(row.date)
    for report in reports:
        covered = by_category.get(report["category"], set())
        report["category_dates_without_value"] = [
            d.isoformat() for d in month_dates(month) if d not in covered]
    return rows, reports


# ---------------------------------------------------------------------------
# 3. Orchestration
# ---------------------------------------------------------------------------

def normalize_month(month: str, month_dir: Path) -> dict[str, Any]:
    index = load_index(month_dir, month)
    manifest = read_csv(month_dir / f"Habit_Evidence_Manifest_{month}.csv", MANIFEST_COLUMNS)
    manifest_rows = [normalize_manifest_row(r, month, index) for r in manifest]
    charts_path = month_dir / f"Habit_Bar_Charts_{month}.json"
    charts = json.loads(charts_path.read_text(encoding="utf-8")) if charts_path.exists() else []
    bar_rows, bar_reports = bar_chart_rows(month_dir, month, index, charts)
    bar_categories = {r.category for r in bar_rows}
    overlap = bar_categories & {r.category for r in manifest_rows}
    if overlap:
        raise EvidenceError(f"Categories have both manifest and bar-chart evidence: {sorted(overlap)}")
    rows = merge_duplicates(manifest_rows + bar_rows)
    return {
        "month": month,
        "rows": rows,
        "bar_reports": bar_reports,
        "calendar_coverage": {c: sorted(f) for c, f in sorted(index.calendar_coverage.items())},
        "index": index.entries,
    }


def write_normalized(result: dict[str, Any], out_dir: Path) -> Path:
    month = result["month"]
    path = out_dir / f"Habit_Evidence_Normalized_{month}.csv"
    write_csv(path, NORMALIZED_COLUMNS, [r.as_dict() for r in result["rows"]])
    meta = {
        "month": month,
        "calendar_coverage": result["calendar_coverage"],
        "bar_charts": result["bar_reports"],
        "rows": len(result["rows"]),
        "api_calls": 0,
    }
    (out_dir / f"Habit_Evidence_Normalized_{month}.json").write_text(
        json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize Habit screenshot evidence for one month.")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--input-dir", type=Path, default=None,
                        help="Evidence folder (default input/Habit/<month>).")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Normalized evidence folder (default output/Raw/Habit/<month>).")
    args = parser.parse_args(argv)
    month_dir = args.input_dir or INPUT_ROOT / args.month
    out_dir = args.output_dir or NORMALIZED_ROOT / args.month
    try:
        result = normalize_month(args.month, month_dir)
        path = write_normalized(result, out_dir)
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Habit evidence {args.month}: {len(result['rows'])} normalized rows")
    for report in result["bar_reports"]:
        print(f"  {report['category']}: {report['slots']} bars, calibrated mean "
              f"{report['calibrated_mean_min']:.2f} vs displayed {report['reference_average_min']:.0f} min "
              f"(factor {report['calibration_factor']:.4f})")
    print(f"Output: {path}")
    print("RESULT: HABIT EVIDENCE NORMALIZED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
