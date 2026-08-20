# FILE: habit_manual_adjustments.py
"""Apply human-approved Habit additions and integration classification removals."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent

INPUT_DIR = PROJECT_ROOT / "input" / "Integrated"
ADJUSTMENT_FILE = INPUT_DIR / "Habit_Manual_Adjustments.csv"

HABIT_DAILY_DIR = (
    PROJECT_ROOT
    / "output"
    / "Daily"
    / "Time"
    / "Habit"
    / "OffDevice"
)

ANALYSIS_DIR = PROJECT_ROOT / "output" / "Analysis" / "Habit"
PRE_ADJUSTMENT_DIR = ANALYSIS_DIR / "PreAdjustment"

INTEGRATION_ADJUSTMENT_DIR = (
    PROJECT_ROOT
    / "output"
    / "Integrated"
    / "Analysis"
    / "Human_Review"
)

STANDARD_CATEGORIES = {
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
}

ANALYTICAL_CATEGORY_MAP = {
    "Offline Work Tracking": (
        "Productivity & Finance",
        "Offline Work Tracking",
    ),
    "Offline Study Tracker": (
        "Education",
        "Offline Study Tracker",
    ),
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Apply human-approved Habit and integration adjustments."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--adjustment-file",
        type=Path,
        default=ADJUSTMENT_FILE,
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def parse_date(value: str) -> date:
    """Parse ISO and common US-formatted dates."""
    value = value.strip()

    for date_format in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(
        f"Invalid date: {value!r}. "
        "Expected YYYY-MM-DD or M/D/YYYY."
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows while ignoring blank and comment lines."""
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        lines = [
            line
            for line in handle
            if line.strip()
            and not line.lstrip().startswith("#")
        ]

    reader = csv.DictReader(lines)

    if reader.fieldnames is None:
        return []

    reader.fieldnames = [
        field.strip()
        for field in reader.fieldnames
    ]

    return [
        {
            key.strip(): (
                value.strip()
                if value is not None
                else ""
            )
            for key, value in row.items()
            if key is not None
        }
        for row in reader
    ]


def load_adjustments(
    path: Path,
    start_date: date,
    end_date: date,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load and validate all human adjustments before any writes."""
    rows = read_csv_rows(path)

    if not rows:
        return {}

    required = {
        "Date",
        "Category",
        "Adjustment_min",
        "Reason",
    }

    missing = required - set(rows[0])

    if missing:
        raise ValueError(
            f"{path} is missing columns: "
            f"{', '.join(sorted(missing))}"
        )

    result: dict[tuple[str, str], dict[str, Any]] = {}

    for line_number, row in enumerate(rows, start=2):
        if not row.get("Date") and not row.get("Category"):
            continue

        target_date = parse_date(row["Date"])

        if not start_date <= target_date <= end_date:
            continue

        category = row["Category"].strip()

        if category not in STANDARD_CATEGORIES:
            raise ValueError(
                f"Unknown Habit category on row "
                f"{line_number}: {category!r}"
            )

        try:
            adjustment_min = float(
                row["Adjustment_min"] or 0
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid Adjustment_min on row "
                f"{line_number}: "
                f"{row['Adjustment_min']!r}"
            ) from exc

        reason = row.get("Reason", "").strip()

        if not reason and adjustment_min != 0:
            raise ValueError(
                f"Reason is required for non-zero adjustment "
                f"on row {line_number}."
            )

        key = (
            target_date.isoformat(),
            category,
        )

        if key in result:
            raise ValueError(
                f"Duplicate adjustment for "
                f"{target_date} / {category}."
            )

        adjustment_type = (
            "HABIT_ADD"
            if adjustment_min > 0
            else "INTEGRATION_REMOVE"
            if adjustment_min < 0
            else "NO_CHANGE"
        )

        analytical_category, analytical_subcategory = (
            ANALYTICAL_CATEGORY_MAP.get(
                category,
                (category, category),
            )
        )

        result[key] = {
            "date": target_date.isoformat(),
            "category": category,
            "adjustment_min": adjustment_min,
            "reason": reason,
            "adjustment_type": adjustment_type,
            "analytical_category": analytical_category,
            "analytical_subcategory": analytical_subcategory,
        }

    return result


def load_daily_file(
    target_date: date,
) -> tuple[Path, list[dict[str, str]]]:
    """Load the Habit daily file for a date."""
    path = (
        HABIT_DAILY_DIR
        / f"Daily_Time_{target_date.isoformat()}.csv"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Habit daily file not found: {path}"
        )

    rows = read_csv_rows(path)

    if not rows:
        raise ValueError(
            f"Habit daily file is empty: {path}"
        )

    required = {
        "Date",
        "Source",
        "Category",
        "Subcategory",
        "Duration_sec",
        "Event_Count",
        "Allocation_Type",
        "Evidence_Type",
    }

    missing = required - set(rows[0])

    if missing:
        raise ValueError(
            f"{path} is missing columns: "
            f"{', '.join(sorted(missing))}"
        )

    return path, rows


def duration_seconds(value: str) -> float:
    """Parse a duration field."""
    try:
        return float(value or 0)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Duration_sec: {value!r}"
        ) from exc


def format_seconds(value: float) -> str:
    """Format seconds for CSV output."""
    if abs(value) < 0.0005:
        return "0"

    return (
        f"{value:.3f}"
        .rstrip("0")
        .rstrip(".")
    )


def apply_habit_addition(
    rows: list[dict[str, str]],
    category: str,
    adjustment_sec: float,
    reason: str,
) -> tuple[float, float]:
    """Add missing time to the Habit daily category."""
    matching = [
        row
        for row in rows
        if row.get("Category", "").strip() == category
    ]

    if not matching:
        raise ValueError(
            f"Category {category!r} not found in "
            "Habit daily file."
        )

    current_total = sum(
        duration_seconds(
            row.get("Duration_sec", "0")
        )
        for row in matching
    )

    corrected_total = (
        current_total + adjustment_sec
    )

    primary = matching[0]

    primary["Duration_sec"] = format_seconds(
        duration_seconds(
            primary.get("Duration_sec", "0")
        )
        + adjustment_sec
    )

    primary["Allocation_Type"] = "Adjusted"

    marker = "Human Manual Habit Adjustment"

    existing_evidence = (
        primary.get("Evidence_Type", "").strip()
    )

    if marker not in existing_evidence:
        primary["Evidence_Type"] = (
            f"{existing_evidence}; {marker}"
            if existing_evidence
            else marker
        )

    source_marker = (
        f"Habit_Manual_Adjustments.csv: {reason}"
    )

    existing_source = (
        primary.get("Evidence_Source", "").strip()
    )

    primary["Evidence_Source"] = (
        f"{existing_source}; {source_marker}"
        if existing_source
        else source_marker
    )

    return current_total, corrected_total


def snapshot_path(target_date: date) -> Path:
    """Return the immutable pre-adjustment snapshot path."""
    return (
        PRE_ADJUSTMENT_DIR
        / target_date.isoformat()
        / f"Daily_Time_{target_date.isoformat()}.csv"
    )


def ensure_pre_adjustment_snapshot(
    target_date: date,
    source_path: Path,
) -> Path:
    """Create a snapshot only once."""
    target = snapshot_path(target_date)

    if target.exists():
        return target

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    target.write_bytes(
        source_path.read_bytes()
    )

    return target


def restore_pre_adjustment_snapshot(
    target_date: date,
    target_path: Path,
) -> None:
    """Restore the original state before reapplying additions."""
    snapshot = snapshot_path(target_date)

    if snapshot.exists():
        target_path.write_bytes(
            snapshot.read_bytes()
        )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """Write CSV rows."""
    if not rows:
        return

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)


def validate_habit_additions(
    grouped: dict[str, list[dict[str, Any]]],
    daily_rows: dict[str, list[dict[str, str]]],
) -> None:
    """Validate every positive Habit adjustment before writing."""
    for date_text, items in grouped.items():
        rows = daily_rows[date_text]

        for item in items:
            if item["adjustment_type"] != "HABIT_ADD":
                continue

            category = item["category"]

            matching = [
                row
                for row in rows
                if row.get("Category", "").strip()
                == category
            ]

            if not matching:
                raise ValueError(
                    f"Category {category!r} not found "
                    f"in Habit daily file for {date_text}."
                )

            adjustment_sec = (
                item["adjustment_min"] * 60
            )

            if adjustment_sec <= 0:
                raise ValueError(
                    "Internal validation error: "
                    "HABIT_ADD must be positive."
                )


def build_integration_removals(
    adjustments: dict[
        tuple[str, str],
        dict[str, Any],
    ],
) -> list[dict[str, Any]]:
    """Build downstream integration classification removals."""
    rows: list[dict[str, Any]] = []

    for item in adjustments.values():
        if item["adjustment_type"] != "INTEGRATION_REMOVE":
            continue

        adjustment_min = item["adjustment_min"]
        removal_min = abs(adjustment_min)

        rows.append(
            {
                "Date": item["date"],
                "Adjustment_Type": "INTEGRATION_REMOVE",
                "Habit_Category": item["category"],
                "Analytical_Category": (
                    item["analytical_category"]
                ),
                "Analytical_Subcategory": (
                    item["analytical_subcategory"]
                ),
                "Adjustment_min": adjustment_min,
                "Removal_min": removal_min,
                "Reason": item["reason"],
                "Review_Status": "APPROVED",
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["Date"],
            row["Habit_Category"],
        ),
    )


def write_integration_removals(
    rows: list[dict[str, Any]],
) -> Path:
    """Write deterministic downstream integration removals."""
    INTEGRATION_ADJUSTMENT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        INTEGRATION_ADJUSTMENT_DIR
        / "Integration_Classification_Removals.csv"
    )

    fields = [
        "Date",
        "Adjustment_Type",
        "Habit_Category",
        "Analytical_Category",
        "Analytical_Subcategory",
        "Adjustment_min",
        "Removal_min",
        "Reason",
        "Review_Status",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)

    return path


def write_audit(
    rows: list[dict[str, Any]],
) -> Path:
    """Write the human-adjustment audit."""
    ANALYSIS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        ANALYSIS_DIR
        / "Habit_Manual_Adjustment_Audit.csv"
    )

    fields = [
        "Date",
        "Adjustment_Type",
        "Category",
        "Adjustment_min",
        "Current_Duration_sec",
        "Corrected_Duration_sec",
        "Analytical_Category",
        "Analytical_Subcategory",
        "Reason",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)

    return path


def main() -> int:
    """Run the complete transactional adjustment process."""
    args = parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if end_date < start_date:
        raise ValueError(
            "End date cannot precede start date."
        )

    adjustments = load_adjustments(
        args.adjustment_file,
        start_date,
        end_date,
    )

    if not adjustments:
        print("No non-empty adjustment rows found.")
        print(
            "RESULT: NO HABIT ADJUSTMENTS APPLIED."
        )
        return 0

    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for item in adjustments.values():
        if item["adjustment_min"] != 0:
            grouped[item["date"]].append(item)

    if not grouped:
        print("All Adjustment_min values are zero.")
        print(
            "RESULT: NO HABIT ADJUSTMENTS APPLIED."
        )
        return 0

    print(
        "=== Habit Manual Adjustments ==="
    )
    print(
        f"Dates      : "
        f"{start_date.isoformat()} -> "
        f"{end_date.isoformat()}"
    )
    print(
        f"Adjustment : "
        f"{args.adjustment_file.resolve()}"
    )
    print()

    daily_rows: dict[
        str,
        list[dict[str, str]],
    ] = {}

    daily_paths: dict[str, Path] = {}

    for date_text in sorted(grouped):
        target_date = parse_date(date_text)

        path, rows = load_daily_file(
            target_date
        )

        daily_paths[date_text] = path

        snapshot = ensure_pre_adjustment_snapshot(
            target_date,
            path,
        )

        if snapshot.exists():
            restore_pre_adjustment_snapshot(
                target_date,
                path,
            )

        _, rows = load_daily_file(
            target_date
        )

        daily_rows[date_text] = rows

    # Validate every positive Habit addition before any write.
    validate_habit_additions(
        grouped,
        daily_rows,
    )

    integration_removals = (
        build_integration_removals(
            adjustments
        )
    )

    audit_rows: list[dict[str, Any]] = []

    # Apply only positive Habit additions.
    for date_text in sorted(grouped):
        rows = daily_rows[date_text]
        path = daily_paths[date_text]

        for item in grouped[date_text]:
            adjustment_min = item["adjustment_min"]

            if item["adjustment_type"] == "HABIT_ADD":
                current_total, corrected_total = (
                    apply_habit_addition(
                        rows,
                        item["category"],
                        adjustment_min * 60,
                        item["reason"],
                    )
                )
            else:
                current_total = sum(
                    duration_seconds(
                        row.get("Duration_sec", "0")
                    )
                    for row in rows
                    if row.get("Category", "").strip()
                    == item["category"]
                )
                corrected_total = current_total

            audit_rows.append(
                {
                    "Date": date_text,
                    "Adjustment_Type": (
                        item["adjustment_type"]
                    ),
                    "Category": item["category"],
                    "Adjustment_min": adjustment_min,
                    "Current_Duration_sec": round(
                        current_total,
                        3,
                    ),
                    "Corrected_Duration_sec": round(
                        corrected_total,
                        3,
                    ),
                    "Analytical_Category": (
                        item["analytical_category"]
                    ),
                    "Analytical_Subcategory": (
                        item["analytical_subcategory"]
                    ),
                    "Reason": item["reason"],
                }
            )

        # Write each date only after every adjustment has
        # passed validation.
        if any(
            item["adjustment_type"] == "HABIT_ADD"
            for item in grouped[date_text]
        ):
            write_csv(path, rows)

        print(
            f"{date_text} | "
            f"{len(grouped[date_text])} adjustments"
        )

    audit_path = write_audit(
        sorted(
            audit_rows,
            key=lambda row: (
                row["Date"],
                row["Category"],
            ),
        )
    )

    integration_path = (
        write_integration_removals(
            integration_removals
        )
    )

    habit_additions = sum(
        1
        for item in adjustments.values()
        if item["adjustment_type"] == "HABIT_ADD"
    )

    integration_removals_count = sum(
        1
        for item in adjustments.values()
        if item["adjustment_type"]
        == "INTEGRATION_REMOVE"
    )

    print()
    print(
        "=== HABIT / INTEGRATION ADJUSTMENT SUMMARY ==="
    )
    print(
        f"Adjustment rows          : "
        f"{len(adjustments)}"
    )
    print(
        f"Habit additions          : "
        f"{habit_additions}"
    )
    print(
        f"Integration removals     : "
        f"{integration_removals_count}"
    )
    print(
        f"Habit audit               : "
        f"{audit_path}"
    )
    print(
        f"Integration removals     : "
        f"{integration_path}"
    )
    print()
    print(
        "RESULT: MANUAL ADJUSTMENTS APPLIED."
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )
        print(
            "RESULT: MANUAL ADJUSTMENTS FAILED."
        )
        raise