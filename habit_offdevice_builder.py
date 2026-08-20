# FILE: habit_offdevice_builder.py

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent

RAW_ROOT = PROJECT_ROOT / "output" / "Raw" / "Habit"
FACT_ROOT = PROJECT_ROOT / "output" / "Fact" / "Time" / "Habit" / "OffDevice"
DAILY_ROOT = PROJECT_ROOT / "output" / "Daily" / "Time" / "Habit" / "OffDevice"
AUDIT_ROOT = PROJECT_ROOT / "output" / "Analysis" / "Habit"

BASELINE_FILE = (
    PROJECT_ROOT
    / "input"
    / "Integrated"
    / "Habit_Initial_Baselines.csv"
)

SOURCE = "habit_offdevice"

STANDARD_CATEGORIES = (
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

TRACKING_MODES = {
    "Workout": "daily",
    "Read a book": "daily",
    "Meditation": "daily",
    "Offline Study Tracker": "daily",
    "Offline Work Tracking": "daily",
    "Family Time Tracking": "weekly_cumulative",
    "Social Time Tracking": "weekly_cumulative",
    "TV Time tracking": "weekly_cumulative",
    "Personal Time Tracking": "weekly_cumulative",
    "Console Time Tracking": "weekly_cumulative",
    "Journaling": "daily",
    "Sleep": "daily",
    "Motorcycle Time": "monthly_cumulative",
}

COLUMNS = [
    "Date",
    "Source",
    "Category",
    "Subcategory",
    "Duration_sec",
    "Event_Count",
    "Allocation_Type",
    "Evidence_Type",
    "Evidence_Source",
    "Tracking_Mode",
    "Current_Value_sec",
    "Previous_Value_sec",
    "Period_Start",
    "Delta_Status",
]

AUDIT_COLUMNS = [
    "Date",
    "Category",
    "Tracking_Mode",
    "Period_Start",
    "Current_Value_sec",
    "Previous_Value_sec",
    "Duration_sec",
    "Delta_Status",
    "Allocation_Type",
    "Evidence_Type",
    "Evidence_Source",
]

OBSERVED = "Observed"
NORMALIZED = "Normalized"
REVIEW = "Review"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build daily Habit time from cumulative tracker state."
    )
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument(
        "--date",
        action="append",
        help="YYYY-MM-DD; repeatable",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def validate_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError(f"Invalid month: {value}")

    year, month = map(int, value.split("-"))
    date(year, month, 1)
    return value


def validate_date(target_date: str, month: str) -> str:
    try:
        parsed = date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date: {target_date}. Expected YYYY-MM-DD."
        ) from exc

    if parsed.strftime("%Y-%m") != month:
        raise ValueError(
            f"Requested date {target_date} is outside month {month}."
        )

    return parsed.isoformat()


def discover_dates(month: str) -> list[str]:
    root = RAW_ROOT / month

    if not root.exists():
        return []

    return sorted(
        path.name
        for path in root.iterdir()
        if (
            path.is_dir()
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
            and (path / "AI_Extraction.json").exists()
        )
    )


def period_start(target_date: str, mode: str) -> str:
    current_date = date.fromisoformat(target_date)

    if mode == "weekly_cumulative":
        return (
            current_date - timedelta(days=current_date.weekday())
        ).isoformat()

    if mode == "monthly_cumulative":
        return current_date.replace(day=1).isoformat()

    return current_date.isoformat()


def fmt(seconds: float) -> str:
    """Format seconds as a compact human-readable duration."""
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)

    parts: list[str] = []

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if remaining_seconds:
        parts.append(f"{remaining_seconds}s")

    return " ".join(parts) if parts else "0s"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return value


def load_states(
    dates: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    states: dict[tuple[str, str], dict[str, Any]] = {}

    for target_date in dates:
        path = (
            RAW_ROOT
            / target_date[:7]
            / target_date
            / "AI_Extraction.json"
        )

        extraction = load_json(path)

        if extraction.get("date") != target_date:
            raise ValueError(f"Date mismatch in {path}")

        categories = extraction.get("categories")

        if not isinstance(categories, list):
            raise ValueError(f"Missing categories in {path}")

        actual_categories = [item.get("category") for item in categories]

        if actual_categories != list(STANDARD_CATEGORIES):
            raise ValueError(f"Taxonomy mismatch in {path}")

        for item in categories:
            category = item["category"]
            expected_mode = TRACKING_MODES[category]
            actual_mode = item.get("tracking_mode")

            if actual_mode != expected_mode:
                raise ValueError(
                    f"Tracking mode mismatch for {category} in {path}: "
                    f"{actual_mode!r} != {expected_mode!r}"
                )

            value = item.get("current_value_sec")

            if not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"Invalid current value for {category} in {path}"
                )

            expected_start = period_start(target_date, expected_mode)
            actual_start = item.get("period_start")

            if actual_start != expected_start:
                raise ValueError(
                    f"Period start mismatch for {category} in {path}: "
                    f"{actual_start!r} != {expected_start!r}"
                )

            states[(target_date, category)] = {
                "date": target_date,
                "category": category,
                "mode": expected_mode,
                "period_start": expected_start,
                "current": value,
                "path": path,
            }

    return states


def load_initial_baselines() -> dict[tuple[str, str], dict[str, Any]]:
    if not BASELINE_FILE.exists():
        return {}

    with BASELINE_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        csv_lines = [
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        ]

    if not csv_lines:
        return {}

    reader = csv.DictReader(csv_lines)

    if reader.fieldnames is None:
        raise ValueError(
            f"Habit_Initial_Baselines.csv has no CSV header: "
            f"{BASELINE_FILE}"
        )

    fieldnames = [
        field.strip()
        for field in reader.fieldnames
        if field is not None
    ]

    required_columns = {
        "Date",
        "Category",
        "Duration_sec",
        "Reason",
    }

    missing = required_columns - set(fieldnames)

    if missing:
        raise ValueError(
            "Habit_Initial_Baselines.csv is missing columns: "
            + ", ".join(sorted(missing))
        )

    baselines: dict[tuple[str, str], dict[str, Any]] = {}

    for row_number, raw_row in enumerate(reader, start=3):
        row = {
            key.strip(): (value.strip() if value is not None else "")
            for key, value in raw_row.items()
            if key is not None
        }

        target_date = row.get("Date", "")
        category = row.get("Category", "")
        duration_text = row.get("Duration_sec", "")
        reason = row.get("Reason", "")

        if not target_date:
            raise ValueError(
                f"Missing Date on CSV line {row_number}."
            )

        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError as exc:
            raise ValueError(
                f"Invalid Date on line {row_number}: "
                f"{target_date!r}"
            ) from exc

        target_date = parsed_date.isoformat()

        if category not in STANDARD_CATEGORIES:
            raise ValueError(
                f"Invalid baseline category on line {row_number}: "
                f"{category!r}"
            )

        mode = TRACKING_MODES[category]

        if mode not in {
            "weekly_cumulative",
            "monthly_cumulative",
        }:
            raise ValueError(
                "Initial baseline may only override cumulative "
                f"trackers: {category}"
            )

        try:
            duration = int(duration_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid Duration_sec on line {row_number}: "
                f"{duration_text!r}"
            ) from exc

        if duration < 0:
            raise ValueError(
                f"Negative Duration_sec on line {row_number}."
            )

        if not reason:
            raise ValueError(
                f"Reason is required on line {row_number}."
            )

        key = (target_date, category)

        if key in baselines:
            raise ValueError(
                f"Duplicate initial baseline: "
                f"{target_date} / {category}"
            )

        baselines[key] = {
            "date": target_date,
            "category": category,
            "duration": duration,
            "reason": reason,
        }

    return baselines

def previous_state(
    current: dict[str, Any],
    states: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    current_date = date.fromisoformat(current["date"])
    category = current["category"]
    start = date.fromisoformat(current["period_start"])

    candidate = current_date - timedelta(days=1)

    while candidate >= start:
        state = states.get((candidate.isoformat(), category))

        if state is not None:
            return state

        candidate -= timedelta(days=1)

    return None


def calculate(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> tuple[int, str]:
    if current["mode"] == "daily":
        return current["current"], "DAILY_VALUE"

    if previous is None:
        return 0, "BASELINE_REVIEW"

    if current["current"] < previous["current"]:
        return 0, "DECREASE_REVIEW"

    delta = current["current"] - previous["current"]

    if delta:
        return delta, "CUMULATIVE_DELTA"

    return 0, "NO_CHANGE"


def build_rows(
    target_date: str,
    states: dict[tuple[str, str], dict[str, Any]],
    initial_baselines: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for category in STANDARD_CATEGORIES:
        state = states.get((target_date, category))

        if state is None:
            mode = TRACKING_MODES[category]
            current = 0
            previous = ""
            duration = 0
            status = "MISSING_CATEGORY"
            allocation = NORMALIZED
            evidence_type = "Missing Standard Category"
            evidence_source = "Habit / OffDevice Taxonomy"
            period = period_start(target_date, mode)

        else:
            mode = state["mode"]
            current = state["current"]
            period = state["period_start"]

            previous_state_value = previous_state(
                state,
                states,
            )

            previous = (
                ""
                if previous_state_value is None
                else previous_state_value["current"]
            )

            baseline = initial_baselines.get(
                (target_date, category)
            )

            if baseline is not None:
                if target_date != baseline["date"]:
                    raise ValueError(
                        "Initial baseline date mismatch."
                    )

                if mode not in {
                    "weekly_cumulative",
                    "monthly_cumulative",
                }:
                    raise ValueError(
                        f"Invalid initial baseline tracker mode "
                        f"for {category}: {mode}"
                    )

                duration = baseline["duration"]
                status = "MANUAL_BASELINE"
                allocation = OBSERVED
                evidence_type = "Verified Manual Initial Baseline"
                evidence_source = (
                    "Habit_Initial_Baselines.csv"
                )

            else:
                duration, status = calculate(
                    state,
                    previous_state_value,
                )

                if status in {
                    "BASELINE_REVIEW",
                    "DECREASE_REVIEW",
                }:
                    allocation = REVIEW
                    evidence_type = (
                        "Cumulative State Baseline / Change Review"
                    )
                    evidence_source = "Habit_State_Audit.csv"

                elif duration > 0:
                    allocation = OBSERVED
                    evidence_type = (
                        "Habit / OffDevice Tracker State"
                    )
                    evidence_source = state["path"].name

                else:
                    allocation = NORMALIZED
                    evidence_type = (
                        "Habit / OffDevice Tracker State"
                    )
                    evidence_source = state["path"].name

        event_count = (
            1
            if allocation == OBSERVED and duration > 0
            else 0
        )

        row = {
            "Date": target_date,
            "Source": SOURCE,
            "Category": category,
            "Subcategory": category,
            "Duration_sec": duration,
            "Event_Count": event_count,
            "Allocation_Type": allocation,
            "Evidence_Type": evidence_type,
            "Evidence_Source": evidence_source,
            "Tracking_Mode": mode,
            "Current_Value_sec": current,
            "Previous_Value_sec": previous,
            "Period_Start": period,
            "Delta_Status": status,
        }

        rows.append(row)

        audit.append({
            "Date": target_date,
            "Category": category,
            "Tracking_Mode": mode,
            "Period_Start": period,
            "Current_Value_sec": current,
            "Previous_Value_sec": previous,
            "Duration_sec": duration,
            "Delta_Status": status,
            "Allocation_Type": allocation,
            "Evidence_Type": evidence_type,
            "Evidence_Source": evidence_source,
        })

    return rows, audit


def csv_bytes(
    rows: list[dict[str, Any]],
    columns: list[str],
) -> bytes:
    buffer = StringIO(newline="")

    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        lineterminator="\n",
    )

    writer.writeheader()
    writer.writerows(rows)

    return buffer.getvalue().encode("utf-8")


def write_changed(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_bytes() == content:
        return "UNCHANGED"

    status = "CHANGED" if path.exists() else "NEW"

    path.write_bytes(content)

    return status


def fact_path(target_date: str) -> Path:
    return FACT_ROOT / f"Fact_Time_{target_date}.csv"


def daily_path(target_date: str) -> Path:
    return DAILY_ROOT / f"Daily_Time_{target_date}.csv"


def metadata_path(target_date: str) -> Path:
    return FACT_ROOT / f"Fact_Time_{target_date}.metadata.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_metadata(
    target_date: str,
    rows: list[dict[str, Any]],
) -> None:
    source = (
        RAW_ROOT
        / target_date[:7]
        / target_date
        / "AI_Extraction.json"
    )

    path = metadata_path(target_date)
    path.parent.mkdir(parents=True, exist_ok=True)

    observed = sum(
        row["Duration_sec"]
        for row in rows
        if row["Allocation_Type"] == OBSERVED
    )

    review = sum(
        1
        for row in rows
        if row["Allocation_Type"] == REVIEW
    )

    manual_baselines = sum(
        1
        for row in rows
        if row["Delta_Status"] == "MANUAL_BASELINE"
    )

    metadata = {
        "date": target_date,
        "source": SOURCE,
        "builder": "habit_offdevice_builder.py",
        "builder_version": 3,
        "canonical_extraction_sha256": sha256(source),
        "initial_baseline_file": str(BASELINE_FILE),
        "tracking_semantics": {
            "weekly_restart": "Monday",
            "monthly_restart": "first day of month",
            "budget_used_as_observed_time": False,
            "baseline_policy": "REVIEW + 0 seconds",
            "manual_initial_baseline_policy": (
                "Verified override from "
                "Habit_Initial_Baselines.csv"
            ),
            "decrease_policy": "REVIEW + 0 seconds",
        },
        "fact": {
            "path": str(fact_path(target_date)),
            "rows": len(rows),
            "duration_sec": sum(
                row["Duration_sec"] for row in rows
            ),
            "observed_duration_sec": observed,
            "review_rows": review,
            "manual_baseline_rows": manual_baselines,
        },
    }

    path.write_text(
        json.dumps(
            metadata,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    try:
        month = validate_month(args.month)

        all_dates = discover_dates(month)

        if not all_dates:
            raise ValueError(
                f"No canonical Habit extractions found for {month}."
            )

        if args.date:
            dates = sorted(
                {
                    validate_date(target_date, month)
                    for target_date in args.date
                }
            )
        else:
            dates = all_dates

        states = load_states(all_dates)
        initial_baselines = load_initial_baselines()

        for (baseline_date, category), baseline in initial_baselines.items():
            if baseline_date[:7] != month:
                continue

            if (baseline_date, category) not in states:
                raise ValueError(
                    "Initial baseline references a date/category "
                    f"without canonical extraction: "
                    f"{baseline_date} / {category}"
                )

        print("# Habit / OffDevice Tracker Builder")
        print(f"Month : {month}")
        print(f"Dates : {', '.join(dates)}")
        print("Weekly cumulative trackers restart every Monday.")
        print("Motorcycle Time restarts on the first day of each month.")
        print("Budgets are never used as observed time.")
        print(
            "First cumulative snapshot of a period is "
            "REVIEW + 0 seconds."
        )

        if initial_baselines:
            print(
                f"Initial baseline overrides : "
                f"{len(initial_baselines)}"
            )

        print()

        audit_rows: list[dict[str, Any]] = []
        results: list[tuple[str, list[dict[str, Any]]]] = []

        for target_date in dates:
            rows, audit = build_rows(
                target_date,
                states,
                initial_baselines,
            )

            audit_rows.extend(audit)

            fact = fact_path(target_date)
            daily = daily_path(target_date)

            status_a = write_changed(
                fact,
                csv_bytes(rows, COLUMNS),
            )

            status_b = write_changed(
                daily,
                csv_bytes(rows, COLUMNS),
            )

            write_metadata(
                target_date,
                rows,
            )

            observed = sum(
                row["Duration_sec"]
                for row in rows
                if row["Allocation_Type"] == OBSERVED
            )

            review_rows = [
                row
                for row in rows
                if row["Allocation_Type"] == REVIEW
            ]

            manual_rows = [
                row
                for row in rows
                if row["Delta_Status"] == "MANUAL_BASELINE"
            ]

            changed = (
                "CHANGED"
                if "CHANGED" in (status_a, status_b)
                else status_a
            )

            print(
                f"{target_date} | {changed} | "
                f"{len(rows)} rows | "
                f"Observed {fmt(observed)} | "
                f"Review rows {len(review_rows)}"
            )

            for row in manual_rows:
                print(
                    f"  MANUAL BASELINE | "
                    f"{row['Category']} | "
                    f"{fmt(int(row['Duration_sec']))}"
                )

            for row in review_rows:
                print(
                    f"  REVIEW | {row['Category']} | "
                    f"{row['Delta_Status']} | "
                    f"current={fmt(int(row['Current_Value_sec']))}"
                )

            results.append(
                (target_date, rows)
            )

        AUDIT_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        audit_file = (
            AUDIT_ROOT
            / f"Habit_State_Audit_{month}.csv"
        )

        write_changed(
            audit_file,
            csv_bytes(audit_rows, AUDIT_COLUMNS),
        )

        total = sum(
            row["Duration_sec"]
            for _, rows in results
            for row in rows
            if row["Allocation_Type"] == OBSERVED
        )

        reviews = sum(
            1
            for _, rows in results
            for row in rows
            if row["Allocation_Type"] == REVIEW
        )

        manual_count = sum(
            1
            for _, rows in results
            for row in rows
            if row["Delta_Status"] == "MANUAL_BASELINE"
        )

        print()
        print("=== HABIT / OFFDEVICE BUILD SUMMARY ===")
        print(f"Dates processed : {len(results)}")
        print(f"Observed        : {fmt(total)}")
        print(f"Review rows     : {reviews}")
        print(f"Manual baselines: {manual_count}")
        print(f"State audit     : {audit_file}")
        print()
        print("RESULT: HABIT / OFFDEVICE BUILD PASSED.")

        return 0

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )
        print(
            "RESULT: HABIT / OFFDEVICE BUILD FAILED."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())