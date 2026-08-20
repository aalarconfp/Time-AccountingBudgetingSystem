# FILE: integration_human_review.py
"""Generate a simple Habit-only human review adjustment CSV."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
INTEGRATED_DIR = PROJECT_ROOT / "output" / "Integrated"
ANALYSIS_DIR = INTEGRATED_DIR / "Analysis"
ADJUSTMENT_FILE = PROJECT_ROOT / "input" / "Integrated" / "Habit_Manual_Adjustments.csv"

HABIT_CATEGORIES = (
    "Workout",
    "Read a book",
    "Meditation",
    "Offline Study Tracker",
    "Offline Work Tracking",
    "Family Time Tracking",
    "Social Time Tracking",
    "TV Time tracking",
    "Personal Time Tracking",
    "Console Time Tracking",
    "Journaling",
    "Sleep",
    "Motorcycle Time",
)

PRELIMINARY_REQUIRED_STATUSES = {
    "OVERLAP_REVIEW",
    "REVIEW_COVERAGE",
    "LOW_COVERAGE",
}

ANALYTICAL_MAP = {
    "Offline Work Tracking": "Productivity & Finance",
    "Offline Study Tracker": "Education",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a simple Habit-only human review CSV."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--preliminary-dir",
        type=Path,
        default=None,
        help="Archived preliminary run directory.",
    )
    parser.add_argument(
        "--force-template",
        action="store_true",
        help="Replace the editable adjustment CSV.",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value!r}.") from exc


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        lines = [
            line for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        ]
    if not lines:
        return []
    reader = csv.DictReader(lines)
    if reader.fieldnames is None:
        return []
    reader.fieldnames = [field.strip() for field in reader.fieldnames]
    return [
        {
            key.strip(): value.strip() if value is not None else ""
            for key, value in row.items()
            if key is not None
        }
        for row in reader
    ]


def parse_float(value: str) -> float:
    return float(value or 0)


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


def preliminary_analysis_path(
    preliminary_dir: Path | None,
) -> Path:
    if preliminary_dir is not None:
        return preliminary_dir / "Daily_Integration_Analysis.csv"
    return ANALYSIS_DIR / "Preliminary" / "Daily_Integration_Analysis.csv"


def integrated_day_path(
    target_date: date,
    preliminary_dir: Path | None,
) -> Path:
    if preliminary_dir is not None:
        candidate = (
            preliminary_dir
            / "Integrated"
            / f"Integrated_Daily_Time_{target_date.isoformat()}.csv"
        )
        if candidate.exists():
            return candidate
    return (
        INTEGRATED_DIR
        / f"Integrated_Daily_Time_{target_date.isoformat()}.csv"
    )


def load_review_days(
    start_date: date,
    end_date: date,
    preliminary_dir: Path | None,
) -> dict[str, str]:
    path = preliminary_analysis_path(preliminary_dir)
    rows = read_csv(path)
    if not rows:
        raise FileNotFoundError(
            f"Preliminary daily analysis not found: {path}"
        )

    required = {"Date", "Overall_Status"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(
            f"Preliminary analysis is missing columns: {', '.join(sorted(missing))}"
        )

    review_days: dict[str, str] = {}
    for row in rows:
        target = parse_date(row["Date"])
        if not start_date <= target <= end_date:
            continue
        status = row["Overall_Status"].strip()
        if status in PRELIMINARY_REQUIRED_STATUSES:
            review_days[target.isoformat()] = status
    return review_days


def load_habit_rows(path: Path) -> dict[str, float]:
    rows = read_csv(path)
    result = {category: 0.0 for category in HABIT_CATEGORIES}
    for row in rows:
        source = (row.get("Source_Name") or "").strip().lower()
        source_legacy = (row.get("Source") or "").strip().lower()
        category = (row.get("Category") or "").strip()
        if (source == "habit" or source_legacy == "habit") and category in result:
            result[category] += parse_float(row.get("Duration_sec", "0"))
    return result


def build_review_rows(
    start_date: date,
    end_date: date,
    preliminary_dir: Path | None,
) -> list[dict[str, str]]:
    review_days = load_review_days(
        start_date,
        end_date,
        preliminary_dir,
    )
    rows: list[dict[str, str]] = []

    current = start_date
    while current <= end_date:
        date_text = current.isoformat()
        if date_text in review_days:
            integrated_path = integrated_day_path(
                current,
                preliminary_dir,
            )
            if not integrated_path.exists():
                raise FileNotFoundError(
                    f"Integrated snapshot missing for review day: {integrated_path}"
                )

            durations = load_habit_rows(integrated_path)
            issue = review_days[date_text]

            for category in HABIT_CATEGORIES:
                rows.append(
                    {
                        "Date": date_text,
                        "Issue_Type": issue,
                        "Category": category,
                        "Current_Duration_min": (
                            f"{durations[category] / 60:.2f}"
                        ),
                        "Adjustment_min": "0",
                        "Reason": "",
                    }
                )
        current += timedelta(days=1)

    return rows


def write_adjustment_file(
    rows: list[dict[str, str]],
    force: bool,
) -> None:
    ADJUSTMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if ADJUSTMENT_FILE.exists() and not force:
        raise FileExistsError(
            f"{ADJUSTMENT_FILE} already exists. "
            "Edit it or rerun with --force-template to replace it."
        )

    with ADJUSTMENT_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Date",
                "Category",
                "Adjustment_min",
                "Reason",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Date": row["Date"],
                    "Category": row["Category"],
                    "Adjustment_min": row["Adjustment_min"],
                    "Reason": row["Reason"],
                }
            )


def write_snapshot(
    rows: list[dict[str, str]],
    start_date: date,
    end_date: date,
) -> Path:
    path = (
        ANALYSIS_DIR
        / f"Habit_Human_Review_{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Date",
                "Issue_Type",
                "Category",
                "Current_Duration_min",
                "Adjustment_min",
                "Reason",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    args = parse_args()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if end_date < start_date:
        raise ValueError("End date cannot precede start date.")

    rows = build_review_rows(
        start_date,
        end_date,
        args.preliminary_dir,
    )
    snapshot = write_snapshot(rows, start_date, end_date)
    write_adjustment_file(rows, args.force_template)

    review_days = sorted({row["Date"] for row in rows})

    print("=== Habit Human-in-the-Loop Review ===")
    print(f"Dates       : {start_date} → {end_date}")
    print(f"Review days : {len(review_days)}")
    print(f"Review rows : {len(rows)}")
    print()
    print("Only Habit categories are included.")
    print("Edit Adjustment_min:")
    print("  positive = add missed time")
    print("  negative = reduce overstated time")
    print("  zero     = no change")
    print()
    print(f"Adjustment CSV : {ADJUSTMENT_FILE}")
    print(f"Review snapshot: {snapshot}")
    print()
    print("Offline Work Tracking → Productivity & Finance")
    print("Offline Study Tracker → Education")
    print()
    print("RESULT: SIMPLE HABIT REVIEW GENERATED.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("RESULT: HABIT HUMAN REVIEW FAILED.")
        raise
