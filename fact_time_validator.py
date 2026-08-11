# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\fact_time_validator.py

"""Validate Fact_Time datasets against Raw ActivityWatch datasets.

The validator checks:

- Dataset and column structure.
- Required field completeness.
- Valid ISO-8601 timestamps.
- Timestamp and duration consistency.
- Duplicate Fact_Time IDs.
- Duplicate source event IDs.
- Fact_Time to Raw_ActivityWatch reconciliation.
- Total duration reconciliation.
- Completed-day processing rules.

Examples:

    python fact_time_validator.py

    python fact_time_validator.py --date 2026-08-10

    python fact_time_validator.py --start-date 2026-08-01 --end-date 2026-08-10

    python fact_time_validator.py --include-today

    python fact_time_validator.py --date 2026-08-10 --strict
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from tracker_config import (
    FACT_TIME_COLUMNS,
    FACT_TIME_DIRECTORY,
    FACT_TIME_OPTIONAL_COLUMNS,
    FACT_TIME_REQUIRED_COLUMNS,
    OUTPUT_DIRECTORY,
    RAW_ACTIVITYWATCH_REQUIRED_COLUMNS,
    TIMESTAMP_TOLERANCE_SECONDS,
    fact_time_path,
    latest_completed_date,
    raw_activitywatch_path,
    today_local,
)


class ValidationResult:
    """Collect validation errors and warnings."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def passed(self) -> bool:
        """Return whether validation passed."""
        return not self.errors

    def error(self, message: str) -> None:
        """Record a validation error."""
        self.errors.append(message)

    def warning(self, message: str) -> None:
        """Record a validation warning."""
        self.warnings.append(message)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate Fact_Time datasets."
    )

    date_group = parser.add_mutually_exclusive_group()

    date_group.add_argument(
        "--date",
        dest="target_date",
        help="Validate one date in YYYY-MM-DD format.",
    )

    date_group.add_argument(
        "--start-date",
        dest="start_date",
        help="Start of an inclusive date range.",
    )

    parser.add_argument(
        "--end-date",
        dest="end_date",
        help="End of an inclusive date range.",
    )

    parser.add_argument(
        "--include-today",
        action="store_true",
        help="Allow validation of today's incomplete data.",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat missing Raw_ActivityWatch files as errors.",
    )

    return parser.parse_args()


def parse_date(
    value: str,
    argument_name: str,
) -> date:
    """Parse a YYYY-MM-DD date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {argument_name} '{value}'. "
            "Expected YYYY-MM-DD."
        ) from exc


def discover_fact_dates() -> list[date]:
    """Discover dates from Fact_Time CSV files."""
    if not FACT_TIME_DIRECTORY.exists():
        return []

    dates: list[date] = []

    prefix = "Fact_Time_"

    for path in FACT_TIME_DIRECTORY.glob(
        f"{prefix}*.csv"
    ):
        date_text = path.stem[len(prefix):]

        try:
            dates.append(
                date.fromisoformat(date_text)
            )
        except ValueError:
            continue

    return sorted(set(dates))


def resolve_target_dates(
    args: argparse.Namespace,
) -> list[date]:
    """Resolve requested dates using the completed-day policy."""
    latest_allowed = (
        today_local()
        if args.include_today
        else latest_completed_date()
    )

    if args.target_date:
        target_date = parse_date(
            args.target_date,
            "--date",
        )

        if target_date > latest_allowed:
            raise ValueError(
                f"{target_date.isoformat()} is the current day "
                "or a future date and is excluded by default. "
                "Use --include-today to explicitly include today."
            )

        return [target_date]

    if args.start_date:
        if not args.end_date:
            raise ValueError(
                "--start-date requires --end-date."
            )

        start_date = parse_date(
            args.start_date,
            "--start-date",
        )

        end_date = parse_date(
            args.end_date,
            "--end-date",
        )

        if end_date < start_date:
            raise ValueError(
                "--end-date cannot be earlier than --start-date."
            )

        if end_date > latest_allowed:
            print(
                f"WARNING: Requested end date "
                f"{end_date.isoformat()} exceeds the latest "
                f"eligible date {latest_allowed.isoformat()}."
            )

            end_date = latest_allowed

        if start_date > end_date:
            raise ValueError(
                "No eligible dates remain after applying "
                "the completed-day rule."
            )

        number_of_days = (
            end_date - start_date
        ).days + 1

        return [
            start_date + timedelta(days=offset)
            for offset in range(number_of_days)
        ]

    return [
        target_date
        for target_date in discover_fact_dates()
        if target_date <= latest_allowed
    ]


def read_csv(
    path: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    """Read a CSV file and return rows and headers."""
    if not path.exists():
        return [], []

    with path.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            return [], []

        return list(reader), list(reader.fieldnames)


def normalize_text(
    value: Any,
) -> str:
    """Return a normalized string value."""
    if value is None:
        return ""

    return str(value).strip()


def parse_timestamp(
    value: str,
) -> datetime:
    """Parse an ISO-8601 timestamp with timezone."""
    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError(
            "timestamp has no timezone"
        )

    return timestamp


def parse_duration(
    value: str,
) -> float:
    """Parse a non-negative duration in seconds."""
    duration = float(value)

    if duration < 0:
        raise ValueError(
            "duration cannot be negative"
        )

    return duration


def calculate_duration(
    rows: list[dict[str, str]],
) -> float:
    """Calculate total duration from dataset rows."""
    total = 0.0

    for row in rows:
        total += parse_duration(
            normalize_text(
                row.get("Duration_sec")
            )
        )

    return total


def format_duration(
    seconds: float,
) -> str:
    """Format seconds as hours and minutes."""
    total_minutes = int(
        round(
            max(seconds, 0.0) / 60
        )
    )

    hours, minutes = divmod(
        total_minutes,
        60,
    )

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m"


def validate_fact_schema(
    headers: list[str],
    path: Path,
    result: ValidationResult,
) -> None:
    """Validate Fact_Time dataset structure."""
    actual_columns = set(headers)

    missing_required = (
        FACT_TIME_REQUIRED_COLUMNS
        - actual_columns
    )

    if missing_required:
        result.error(
            f"{path.name}: missing required columns: "
            f"{sorted(missing_required)}"
        )

    missing_optional = (
        FACT_TIME_OPTIONAL_COLUMNS
        - actual_columns
    )

    if missing_optional:
        result.error(
            f"{path.name}: missing schema columns: "
            f"{sorted(missing_optional)}"
        )

    if headers != FACT_TIME_COLUMNS:
        result.warning(
            f"{path.name}: column order differs from "
            "the canonical Fact_Time schema."
        )


def validate_raw_schema(
    headers: list[str],
    path: Path,
    result: ValidationResult,
) -> None:
    """Validate Raw ActivityWatch dataset structure."""
    actual_columns = set(headers)

    missing_required = (
        RAW_ACTIVITYWATCH_REQUIRED_COLUMNS
        - actual_columns
    )

    if missing_required:
        result.error(
            f"{path.name}: missing required columns: "
            f"{sorted(missing_required)}"
        )


def validate_fact_rows(
    rows: list[dict[str, str]],
    target_date: date,
    path: Path,
    result: ValidationResult,
) -> dict[str, Any]:
    """Validate individual Fact_Time rows."""
    expected_date = target_date.isoformat()

    fact_ids: set[str] = set()

    source_keys: set[tuple[str, str]] = set()

    total_duration = 0.0

    first_start: datetime | None = None
    last_end: datetime | None = None

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        prefix = (
            f"{path.name} row {row_number}"
        )

        fact_id = normalize_text(
            row.get("Fact_Time_ID")
        )

        if not fact_id:
            result.error(
                f"{prefix}: missing required value "
                "'Fact_Time_ID'."
            )
        elif fact_id in fact_ids:
            result.error(
                f"{prefix}: duplicate Fact_Time_ID "
                f"'{fact_id}'."
            )
        else:
            fact_ids.add(fact_id)

        row_date = normalize_text(
            row.get("Date")
        )

        if row_date != expected_date:
            result.error(
                f"{prefix}: Date='{row_date}', "
                f"expected '{expected_date}'."
            )

        for required_column in FACT_TIME_REQUIRED_COLUMNS:
            if not normalize_text(
                row.get(required_column)
            ):
                result.error(
                    f"{prefix}: missing required value "
                    f"'{required_column}'."
                )

        source = normalize_text(
            row.get("Source")
        )

        source_event_id = normalize_text(
            row.get("Source_Event_ID")
        )

        if source and source_event_id:
            source_key = (
                source,
                source_event_id,
            )

            if source_key in source_keys:
                result.error(
                    f"{prefix}: duplicate source event "
                    f"'{source}/{source_event_id}'."
                )

            source_keys.add(source_key)

        try:
            start = parse_timestamp(
                normalize_text(
                    row.get("Start")
                )
            )

            end = parse_timestamp(
                normalize_text(
                    row.get("End")
                )
            )

            duration = parse_duration(
                normalize_text(
                    row.get("Duration_sec")
                )
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            result.error(
                f"{prefix}: invalid timestamp/duration: "
                f"{exc}"
            )
            continue

        if end < start:
            result.error(
                f"{prefix}: End is earlier than Start."
            )
            continue

        calculated_duration = (
            end - start
        ).total_seconds()

        if abs(
            calculated_duration - duration
        ) > TIMESTAMP_TOLERANCE_SECONDS:
            result.error(
                f"{prefix}: duration mismatch. "
                f"Duration_sec={duration:.3f}, "
                f"timestamp difference="
                f"{calculated_duration:.3f}."
            )

        total_duration += duration

        if (
            first_start is None
            or start < first_start
        ):
            first_start = start

        if (
            last_end is None
            or end > last_end
        ):
            last_end = end

    return {
        "rows": len(rows),
        "fact_ids": len(fact_ids),
        "source_keys": len(source_keys),
        "duration": total_duration,
        "first_start": first_start,
        "last_end": last_end,
    }


def build_source_keys(
    rows: list[dict[str, str]],
    source_column: str,
    event_id_column: str,
) -> set[tuple[str, str]]:
    """Build source/event ID pairs."""
    return {
        (
            normalize_text(
                row.get(source_column)
            ),
            normalize_text(
                row.get(event_id_column)
            ),
        )
        for row in rows
        if normalize_text(
            row.get(source_column)
        )
        and normalize_text(
            row.get(event_id_column)
        )
    }


def validate_source_reconciliation(
    fact_rows: list[dict[str, str]],
    raw_rows: list[dict[str, str]],
    target_date: date,
    raw_path: Path,
    result: ValidationResult,
) -> dict[str, Any]:
    """Reconcile Fact_Time rows with Raw ActivityWatch rows."""
    raw_keys = build_source_keys(
        rows=raw_rows,
        source_column="Source",
        event_id_column="AW_Event_ID",
    )

    fact_keys = build_source_keys(
        rows=fact_rows,
        source_column="Source",
        event_id_column="Source_Event_ID",
    )

    missing_from_raw = (
        fact_keys - raw_keys
    )

    missing_from_fact = (
        raw_keys - fact_keys
    )

    if missing_from_raw:
        result.error(
            f"{target_date.isoformat()}: "
            f"{len(missing_from_raw):,} Fact_Time "
            "source events do not exist in Raw_ActivityWatch."
        )

    if missing_from_fact:
        result.error(
            f"{target_date.isoformat()}: "
            f"{len(missing_from_fact):,} Raw ActivityWatch "
            "events are missing from Fact_Time."
        )

    raw_duration = 0.0

    for row_number, row in enumerate(
        raw_rows,
        start=2,
    ):
        try:
            raw_duration += parse_duration(
                normalize_text(
                    row.get("Duration_sec")
                )
            )
        except ValueError as exc:
            result.error(
                f"{raw_path.name} row {row_number}: "
                f"invalid duration: {exc}"
            )

    fact_duration = calculate_duration(
        fact_rows
    )

    if abs(
        raw_duration - fact_duration
    ) > TIMESTAMP_TOLERANCE_SECONDS:
        result.error(
            f"{target_date.isoformat()}: total duration mismatch. "
            f"Raw={raw_duration:.3f}s, "
            f"Fact_Time={fact_duration:.3f}s."
        )

    return {
        "raw_rows": len(raw_rows),
        "fact_rows": len(fact_rows),
        "raw_duration": raw_duration,
        "fact_duration": fact_duration,
        "missing_from_raw": len(missing_from_raw),
        "missing_from_fact": len(missing_from_fact),
    }


def validate_one_date(
    target_date: date,
    result: ValidationResult,
    strict: bool,
) -> dict[str, Any]:
    """Validate one date."""
    fact_path = fact_time_path(
        target_date
    )

    raw_path = raw_activitywatch_path(
        target_date
    )

    print()
    print(
        f"--- {target_date.isoformat()} ---"
    )

    print(
        f"Fact_Time : {fact_path}"
    )

    print(
        f"Raw       : {raw_path}"
    )

    if not fact_path.exists():
        result.error(
            f"{target_date.isoformat()}: "
            f"Fact_Time file not found: {fact_path}"
        )

        print(
            "FAIL  Fact_Time file not found."
        )

        return {
            "status": "missing_fact",
            "fact_rows": 0,
            "raw_rows": 0,
            "duration": 0.0,
        }

    fact_rows, fact_headers = read_csv(
        fact_path
    )

    validate_fact_schema(
        headers=fact_headers,
        path=fact_path,
        result=result,
    )

    fact_summary = validate_fact_rows(
        rows=fact_rows,
        target_date=target_date,
        path=fact_path,
        result=result,
    )

    print(
        f"Fact_Time rows : "
        f"{len(fact_rows):,}"
    )

    if not raw_path.exists():
        message = (
            f"{target_date.isoformat()}: "
            f"Raw ActivityWatch source file not found: "
            f"{raw_path}"
        )

        if strict:
            result.error(message)
            print(
                "FAIL  Raw ActivityWatch source not found."
            )
        else:
            result.warning(message)
            print(
                "WARN  Raw ActivityWatch source not found."
            )

        return {
            "status": "missing_raw",
            "fact_rows": len(fact_rows),
            "raw_rows": 0,
            "duration": fact_summary["duration"],
        }

    raw_rows, raw_headers = read_csv(
        raw_path
    )

    validate_raw_schema(
        headers=raw_headers,
        path=raw_path,
        result=result,
    )

    print(
        f"Raw rows      : "
        f"{len(raw_rows):,}"
    )

    reconciliation = (
        validate_source_reconciliation(
            fact_rows=fact_rows,
            raw_rows=raw_rows,
            target_date=target_date,
            raw_path=raw_path,
            result=result,
        )
    )

    print(
        f"Fact duration : "
        f"{format_duration(fact_summary['duration'])}"
    )

    print(
        f"Raw duration  : "
        f"{format_duration(reconciliation['raw_duration'])}"
    )

    if result.passed:
        print(
            "PASS  Date passed validation."
        )
    else:
        print(
            "FAIL  Validation errors detected."
        )

    return {
        "status": (
            "pass"
            if result.passed
            else "fail"
        ),
        "fact_rows": len(fact_rows),
        "raw_rows": len(raw_rows),
        "duration": fact_summary["duration"],
    }


def print_summary(
    target_dates: list[date],
    result: ValidationResult,
) -> None:
    """Print the final validation summary."""
    print()
    print("=" * 60)
    print("=== Fact_Time Validation Summary ===")

    print(
        f"Dates checked : "
        f"{len(target_dates):,}"
    )

    print(
        f"Errors        : "
        f"{len(result.errors):,}"
    )

    print(
        f"Warnings      : "
        f"{len(result.warnings):,}"
    )

    if result.errors:
        print()
        print("=== Errors ===")

        for error in result.errors:
            print(
                f"FAIL  {error}"
            )

    if result.warnings:
        print()
        print("=== Warnings ===")

        for warning in result.warnings:
            print(
                f"WARN  {warning}"
            )

    print()
    print("=== Diagnostic Result ===")

    if result.passed:
        print(
            "PASS  Fact_Time validation completed successfully."
        )

        print(
            "RESULT: FACT_TIME VALIDATION PASSED."
        )

    else:
        print(
            "FAIL  Fact_Time validation found data integrity issues."
        )

        print(
            "RESULT: FACT_TIME VALIDATION FAILED."
        )


def main() -> int:
    """Run Fact_Time validation."""
    args = parse_arguments()

    try:
        target_dates = resolve_target_dates(
            args
        )

        print("# Fact_Time Validator")
        print()

        if not target_dates:
            print(
                "Dates : No Fact_Time datasets found."
            )
        elif len(target_dates) == 1:
            print(
                f"Date  : "
                f"{target_dates[0].isoformat()}"
            )
        else:
            print(
                f"Dates : "
                f"{target_dates[0].isoformat()} → "
                f"{target_dates[-1].isoformat()}"
            )

        print(
            "Mode  : "
            + (
                "INCLUDES CURRENT DAY"
                if args.include_today
                else "COMPLETED DAYS ONLY"
            )
        )

        print(
            f"Output: {OUTPUT_DIRECTORY}"
        )

        print(
            f"Fact  : {FACT_TIME_DIRECTORY}"
        )

        if not target_dates:
            print()
            print(
                "RESULT: NO FACT_TIME DATASETS FOUND."
            )
            return 1

        result = ValidationResult()

        for target_date in target_dates:
            validate_one_date(
                target_date=target_date,
                result=result,
                strict=args.strict,
            )

        print_summary(
            target_dates=target_dates,
            result=result,
        )

        return 0 if result.passed else 1

    except KeyboardInterrupt:
        print()
        print("Cancelled.")
        return 130

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())