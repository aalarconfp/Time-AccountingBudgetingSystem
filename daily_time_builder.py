# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\daily_time_builder.py

"""Build the Daily_Time analytical layer from Fact_Time datasets.

Daily_Time aggregates event-level Fact_Time records into daily
Category/Subcategory totals.

The builder is intentionally separate from Fact_Time. Fact_Time remains
the detailed event-level source, while Daily_Time is an analytical
summary designed for daily, weekly, and monthly reporting.

Missing Fact_Time datasets are reported as NO DATA rather than being
interpreted as zero activity.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from tracker_config import (
    FACT_TIME_DIRECTORY,
    ensure_output_directories,
    fact_time_path,
    latest_completed_date,
    today_local,
    validate_completed_date,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parent
OUTPUT_DIRECTORY = (
    PROJECT_DIRECTORY / "output" / "Daily_Time"
)
DAILY_TIME_FILE = (
    OUTPUT_DIRECTORY / "Daily_Time.csv"
)

FACT_TIME_REQUIRED_COLUMNS = {
    "Fact_Time_ID",
    "Date",
    "Start",
    "End",
    "Duration_sec",
    "Device",
    "Source",
    "Source_Bucket",
    "Source_Event_ID",
    "App",
    "Window_Title",
    "Category",
    "Subcategory",
}

DAILY_TIME_COLUMNS = [
    "Date",
    "Category",
    "Subcategory",
    "Duration_sec",
    "Duration_min",
    "Duration_hours",
    "Event_Count",
]


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build Daily_Time from Fact_Time datasets."
    )

    date_group = parser.add_mutually_exclusive_group()

    date_group.add_argument(
        "--date",
        dest="target_date",
        help="Build one date: YYYY-MM-DD.",
    )

    date_group.add_argument(
        "--days",
        type=int,
        help=(
            "Build the specified number of dates ending "
            "with the latest eligible date."
        ),
    )

    date_group.add_argument(
        "--start-date",
        dest="start_date",
        help="Inclusive start date: YYYY-MM-DD.",
    )

    parser.add_argument(
        "--end-date",
        dest="end_date",
        help="Inclusive end date: YYYY-MM-DD.",
    )

    parser.add_argument(
        "--include-today",
        action="store_true",
        help="Allow processing today's incomplete data.",
    )

    return parser.parse_args()


def parse_date(
    value: str,
    argument_name: str,
) -> date:
    """Parse a YYYY-MM-DD value."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {argument_name}: '{value}'. "
            "Expected YYYY-MM-DD."
        ) from exc


def resolve_target_dates(
    args: argparse.Namespace,
) -> list[date]:
    """Resolve command-line arguments into target dates."""
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

        validate_completed_date(
            target_date,
            include_today=args.include_today,
        )

        return [target_date]

    if args.days is not None:
        if args.days < 1:
            raise ValueError(
                "--days must be at least 1."
            )

        first_date = latest_allowed - timedelta(
            days=args.days - 1,
        )

        return [
            first_date + timedelta(days=offset)
            for offset in range(args.days)
        ]

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
                "--end-date cannot be earlier than "
                "--start-date."
            )

        if end_date > latest_allowed:
            if args.include_today:
                end_date = latest_allowed
            else:
                print(
                    f"WARNING: End date {end_date.isoformat()} "
                    f"is not eligible."
                )
                print(
                    f"Limiting end date to "
                    f"{latest_allowed.isoformat()}."
                )
                end_date = latest_allowed

        if start_date > end_date:
            raise ValueError(
                "No eligible dates remain in the requested range."
            )

        return [
            start_date + timedelta(days=offset)
            for offset in range(
                (end_date - start_date).days + 1
            )
        ]

    return [latest_allowed]


def read_csv(
    path: Path,
) -> list[dict[str, str]]:
    """Read a CSV file."""
    if not path.exists():
        return []

    with path.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError(
                f"CSV has no header: {path}"
            )

        return list(reader)


def write_csv_atomic(
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write CSV data atomically."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8-sig",
            dir=path.parent,
            prefix=f".{path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            writer = csv.DictWriter(
                temporary_file,
                fieldnames=DAILY_TIME_COLUMNS,
                extrasaction="raise",
            )

            writer.writeheader()
            writer.writerows(rows)

            temporary_file.flush()
            os.fsync(
                temporary_file.fileno()
            )

        os.replace(
            temporary_path,
            path,
        )

    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

        raise


def validate_fact_time_schema(
    rows: list[dict[str, str]],
    path: Path,
) -> None:
    """Validate the Fact_Time input schema."""
    if not rows:
        return

    columns = set(rows[0].keys())

    missing = (
        FACT_TIME_REQUIRED_COLUMNS - columns
    )

    if missing:
        raise ValueError(
            f"Fact_Time file is missing required columns: "
            f"{sorted(missing)}\n"
            f"File: {path}"
        )


def normalize_text(
    value: Any,
) -> str:
    """Return a normalized string."""
    if value is None:
        return ""

    return str(value).strip()


def parse_duration(
    value: str,
    row_number: int,
    path: Path,
) -> float:
    """Parse and validate Duration_sec."""
    try:
        duration = float(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Duration_sec in {path}, "
            f"row {row_number}: '{value}'."
        ) from exc

    if duration < 0:
        raise ValueError(
            f"Negative Duration_sec in {path}, "
            f"row {row_number}: {duration}."
        )

    return duration


def aggregate_fact_time(
    rows: list[dict[str, str]],
    target_date: date,
    path: Path,
) -> list[dict[str, Any]]:
    """Aggregate Fact_Time records by category and subcategory."""
    expected_date = target_date.isoformat()

    aggregates: defaultdict[
        tuple[str, str],
        dict[str, float | int],
    ] = defaultdict(
        lambda: {
            "Duration_sec": 0.0,
            "Event_Count": 0,
        }
    )

    seen_event_ids: set[str] = set()

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        row_date = normalize_text(
            row.get("Date")
        )

        if row_date != expected_date:
            raise ValueError(
                f"Fact_Time row {row_number} in {path} "
                f"has Date '{row_date}', expected "
                f"'{expected_date}'."
            )

        event_id = normalize_text(
            row.get("Fact_Time_ID")
        )

        if not event_id:
            raise ValueError(
                f"Fact_Time row {row_number} in {path} "
                "is missing Fact_Time_ID."
            )

        if event_id in seen_event_ids:
            raise ValueError(
                f"Duplicate Fact_Time_ID '{event_id}' "
                f"in {path}, row {row_number}."
            )

        seen_event_ids.add(event_id)

        category = (
            normalize_text(
                row.get("Category")
            )
            or "Uncategorized"
        )

        subcategory = normalize_text(
            row.get("Subcategory")
        )

        duration = parse_duration(
            normalize_text(
                row.get("Duration_sec")
            ),
            row_number,
            path,
        )

        key = (
            category,
            subcategory,
        )

        aggregates[key]["Duration_sec"] += duration
        aggregates[key]["Event_Count"] += 1

    result: list[dict[str, Any]] = []

    for (
        category,
        subcategory,
    ), values in sorted(
        aggregates.items(),
        key=lambda item: (
            item[0][0],
            item[0][1],
        ),
    ):
        duration_sec = float(
            values["Duration_sec"]
        )

        result.append(
            {
                "Date": expected_date,
                "Category": category,
                "Subcategory": subcategory,
                "Duration_sec": round(
                    duration_sec,
                    3,
                ),
                "Duration_min": round(
                    duration_sec / 60,
                    3,
                ),
                "Duration_hours": round(
                    duration_sec / 3600,
                    4,
                ),
                "Event_Count": int(
                    values["Event_Count"]
                ),
            }
        )

    return result


def load_existing_daily_time() -> list[dict[str, str]]:
    """Load the existing Daily_Time dataset."""
    if not DAILY_TIME_FILE.exists():
        return []

    with DAILY_TIME_FILE.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError(
                f"CSV has no header: {DAILY_TIME_FILE}"
            )

        missing = (
            set(DAILY_TIME_COLUMNS)
            - set(reader.fieldnames)
        )

        if missing:
            raise ValueError(
                "Daily_Time file is missing required "
                f"columns: {sorted(missing)}"
            )

        return list(reader)


def replace_dates(
    existing_rows: list[dict[str, str]],
    target_dates: set[date],
    new_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace existing summaries for the processed dates."""
    target_date_strings = {
        target.isoformat()
        for target in target_dates
    }

    retained = [
        {
            column: row.get(column, "")
            for column in DAILY_TIME_COLUMNS
        }
        for row in existing_rows
        if normalize_text(row.get("Date"))
        not in target_date_strings
    ]

    retained.extend(new_rows)

    retained.sort(
        key=lambda row: (
            str(row["Date"]),
            str(row["Category"]),
            str(row["Subcategory"]),
        )
    )

    return retained


def format_duration(
    seconds: float,
) -> str:
    """Format seconds as hours and minutes."""
    total_minutes = int(
        round(max(seconds, 0.0) / 60)
    )

    hours, minutes = divmod(
        total_minutes,
        60,
    )

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m"


def build_dates(
    dates: list[date],
) -> tuple[
    list[dict[str, Any]],
    list[date],
]:
    """Build Daily_Time rows for the requested dates."""
    new_rows: list[dict[str, Any]] = []
    no_data_dates: list[date] = []

    for target_date in dates:
        print()
        print(
            f"--- {target_date.isoformat()} ---"
        )

        fact_path = fact_time_path(
            target_date
        )

        print(
            f"Fact_Time input : {fact_path}"
        )

        if not fact_path.exists():
            print(
                "Result: NO DATA — Fact_Time dataset "
                "does not exist for this date."
            )

            no_data_dates.append(
                target_date
            )
            continue

        fact_rows = read_csv(
            fact_path
        )

        validate_fact_time_schema(
            fact_rows,
            fact_path,
        )

        print(
            f"Fact_Time rows  : {len(fact_rows):,}"
        )

        daily_rows = aggregate_fact_time(
            fact_rows,
            target_date,
            fact_path,
        )

        duration = sum(
            float(row["Duration_sec"])
            for row in daily_rows
        )

        print(
            f"Daily categories: {len(daily_rows):,}"
        )

        print(
            f"Total time      : "
            f"{format_duration(duration)}"
        )

        new_rows.extend(
            daily_rows
        )

    return (
        new_rows,
        no_data_dates,
    )


def print_category_summary(
    rows: list[dict[str, Any]],
) -> None:
    """Print category-level totals."""
    totals: defaultdict[
        str,
        float,
    ] = defaultdict(float)

    for row in rows:
        totals[
            str(row["Category"])
        ] += float(
            row["Duration_sec"]
        )

    total_seconds = sum(
        totals.values()
    )

    if total_seconds <= 0:
        return

    print()
    print("=== Category Summary ===")

    for category, seconds in sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        percentage = (
            seconds / total_seconds * 100
        )

        print(
            f"{format_duration(seconds):>7} "
            f"{percentage:5.1f}%  "
            f"{category}"
        )


def main() -> int:
    """Build Daily_Time datasets."""
    try:
        args = parse_arguments()

        ensure_output_directories()
        OUTPUT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        dates = resolve_target_dates(
            args
        )

        first_date = dates[0]
        last_date = dates[-1]

        print("# Daily_Time Builder")
        print()

        if len(dates) == 1:
            print(
                f"Date   : {first_date.isoformat()}"
            )
        else:
            print(
                f"Dates  : {first_date.isoformat()} → "
                f"{last_date.isoformat()}"
            )

        print(
            f"Range  : {first_date.isoformat()} → "
            f"{(last_date + timedelta(days=1)).isoformat()}"
        )

        print(
            "Mode   : "
            + (
                "INCLUDES CURRENT DAY"
                if args.include_today
                else "COMPLETED DAYS ONLY"
            )
        )

        print()
        print("=== Configuration ===")
        print(
            f"Fact input : {FACT_TIME_DIRECTORY}"
        )
        print(
            f"Daily output: {DAILY_TIME_FILE}"
        )

        new_rows, no_data_dates = build_dates(
            dates
        )

        existing_rows = (
            load_existing_daily_time()
        )

        final_rows = replace_dates(
            existing_rows,
            set(dates),
            new_rows,
        )

        write_csv_atomic(
            final_rows,
            DAILY_TIME_FILE,
        )

        processed_dates = (
            len(dates)
            - len(no_data_dates)
        )

        total_seconds = sum(
            float(row["Duration_sec"])
            for row in new_rows
        )

        print()
        print("=" * 60)
        print("=== Daily_Time Build Summary ===")
        print(
            f"Dates requested       : {len(dates):,}"
        )
        print(
            f"Dates with data       : {processed_dates:,}"
        )
        print(
            f"Dates without data    : "
            f"{len(no_data_dates):,}"
        )
        print(
            f"Daily summary rows    : "
            f"{len(new_rows):,}"
        )
        print(
            f"Final Daily_Time rows : "
            f"{len(final_rows):,}"
        )
        print(
            f"Total analyzed time   : "
            f"{format_duration(total_seconds)}"
        )
        print(
            f"Output                : "
            f"{DAILY_TIME_FILE}"
        )

        if no_data_dates:
            print()
            print("No-data dates:")

            for missing_date in no_data_dates:
                print(
                    f"  - {missing_date.isoformat()}"
                )

        print_category_summary(
            new_rows
        )

        print()
        print(
            "RESULT: Daily_Time datasets "
            "were built successfully."
        )

        return 0

    except KeyboardInterrupt:
        print()
        print(
            "Cancelled."
        )
        return 130

    except Exception as exc:
        print(
            f"\nERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())