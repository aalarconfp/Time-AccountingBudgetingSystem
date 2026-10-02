# FILE: daily_time_builder.py

"""Build source-specific Daily_Time datasets from canonical Fact_Time data.

The builder consumes the canonical Fact_Time layer and produces one
deterministic Daily_Time CSV per calendar date.

Input:
    output/Fact/Time/<source>/<device>/Fact_Time_YYYY-MM-DD.csv

Output:
    output/Daily/Time/<source>/<device>/Daily_Time_YYYY-MM-DD.csv

Daily_Time preserves the established seven-column schema:

    Date
    Category
    Subcategory
    Duration_sec
    Duration_min
    Duration_hours
    Event_Count

iPhone (Apple Screen Time) is refused: its Daily_Time carries provenance
(Allocation_Type, Evidence_Type, Evidence_Source) that this seven-column
schema would erase, so it is produced only by iphone_screen_time_builder.py
(observed days) and apple_screen_time_finalize.py (estimated days).
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config.paths import DAILY_ROOT, FACT_TIME_ROOT
from config.sources import SourceDefinition, SourceType, get_source_definition
from config.tracker_config import DEFAULT_TIMEZONE


DAILY_TIME_COLUMNS = [
    "Date",
    "Category",
    "Subcategory",
    "Duration_sec",
    "Duration_min",
    "Duration_hours",
    "Event_Count",
]


def parse_target_date(value: str | None) -> date:
    """Parse a target date or use today's date in the project timezone."""
    if value is None:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def get_project_timezone() -> ZoneInfo:
    """Return the configured project timezone."""
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load configured timezone '{DEFAULT_TIMEZONE}'."
        ) from exc


def latest_completed_date() -> date:
    """Return the most recent completed local calendar date."""
    return (
        datetime.now(get_project_timezone()).date()
        - timedelta(days=1)
    )


def validate_completed_date(target_date: date) -> None:
    """Reject a date that has not yet fully completed."""
    latest_date = latest_completed_date()

    if target_date > latest_date:
        raise ValueError(
            f"Date {target_date.isoformat()} is not a completed day. "
            f"The latest completed date is {latest_date.isoformat()}."
        )


def ensure_generic_build_allowed(source: SourceDefinition) -> None:
    """Refuse sources whose Daily_Time is owned by a dedicated pipeline."""
    if source.source == SourceType.APPLE_SCREEN_TIME:
        raise ValueError(
            "iPhone Daily_Time must not be built by daily_time_builder.py: "
            "its seven-column schema would erase Allocation_Type, "
            "Evidence_Type and Evidence_Source (estimated and derived rows "
            "would become Observed). Use iphone_screen_time_builder.py for "
            "observed days and apple_screen_time_finalize.py for estimated "
            "days. No files were read or written."
        )


def resolve_source_directory_name(source: SourceDefinition) -> str:
    """Return the stable directory name used for a source definition."""
    if source.device:
        return source.device

    return source.source.value


def get_fact_time_directory(source: SourceDefinition) -> Path:
    """Return the canonical Fact_Time directory for a source."""
    return (
        FACT_TIME_ROOT
        / source.source.value
        / resolve_source_directory_name(source)
    )


def get_daily_time_directory(source: SourceDefinition) -> Path:
    """Return the canonical Daily_Time directory for a source."""
    return (
        DAILY_ROOT
        / "Time"
        / source.source.value
        / resolve_source_directory_name(source)
    )


def get_fact_time_path(
    source: SourceDefinition,
    target_date: date,
) -> Path:
    """Return the canonical Fact_Time path for a date."""
    return (
        get_fact_time_directory(source)
        / f"Fact_Time_{target_date.isoformat()}.csv"
    )


def get_daily_time_path(
    source: SourceDefinition,
    target_date: date,
) -> Path:
    """Return the canonical Daily_Time path for a date."""
    return (
        get_daily_time_directory(source)
        / f"Daily_Time_{target_date.isoformat()}.csv"
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build source-specific Daily_Time datasets from "
            "canonical Fact_Time CSV files."
        )
    )

    parser.add_argument(
        "--date",
        dest="target_date",
        help=(
            "Calendar date to build in YYYY-MM-DD format. "
            "Defaults to the latest completed date."
        ),
    )

    parser.add_argument(
        "--start-date",
        help=(
            "First calendar date to build in YYYY-MM-DD format. "
            "Use with --end-date."
        ),
    )

    parser.add_argument(
        "--end-date",
        help=(
            "Last calendar date to build in YYYY-MM-DD format. "
            "Use with --start-date."
        ),
    )

    parser.add_argument(
        "--source",
        choices=[
            "asus_laptop",
            "desktop",
            "iphone",
            "habit",
        ],
        default="asus_laptop",
        help=(
            "Configured source. Default: asus_laptop. "
            "iphone is refused (its Daily_Time is built by the iPhone pipeline)."
        ),
    )

    return parser.parse_args()


def parse_date_range(
    args: argparse.Namespace,
) -> tuple[date, date]:
    """Resolve the requested date or date range."""
    if args.target_date and (
        args.start_date or args.end_date
    ):
        raise ValueError(
            "--date cannot be combined with --start-date or --end-date."
        )

    if args.start_date and not args.end_date:
        raise ValueError(
            "--start-date requires --end-date."
        )

    if args.end_date and not args.start_date:
        raise ValueError(
            "--end-date requires --start-date."
        )

    if args.start_date and args.end_date:
        start_date = parse_target_date(args.start_date)
        end_date = parse_target_date(args.end_date)

        if end_date < start_date:
            raise ValueError(
                "--end-date cannot be earlier than --start-date."
            )

        return start_date, end_date

    if args.target_date:
        target_date = parse_target_date(args.target_date)
        return target_date, target_date

    target_date = latest_completed_date()
    return target_date, target_date


def get_date_range(
    start_date: date,
    end_date: date,
) -> list[date]:
    """Return every calendar date in an inclusive date range."""
    number_of_days = (end_date - start_date).days

    return [
        start_date + timedelta(days=offset)
        for offset in range(number_of_days + 1)
    ]


def validate_fact_time_columns(
    fieldnames: list[str] | None,
    path: Path,
) -> None:
    """Validate the Fact_Time columns required by Daily_Time."""
    required_columns = {
        "Date",
        "Duration_sec",
        "Category",
        "Subcategory",
    }

    actual_columns = set(fieldnames or [])
    missing_columns = sorted(required_columns - actual_columns)

    if missing_columns:
        raise ValueError(
            "Fact_Time file is missing required columns: "
            f"{missing_columns}\n"
            f"File: {path}"
        )


def parse_duration(value: str, path: Path) -> float:
    """Parse and validate a Fact_Time duration."""
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid Duration_sec value '{value}' in {path}."
        ) from exc

    if duration < 0:
        raise ValueError(
            f"Negative Duration_sec value '{duration}' in {path}."
        )

    return duration


def normalize_dimension(value: str | None) -> str:
    """Normalize an aggregation dimension while preserving empty values."""
    if value is None:
        return ""

    return str(value).strip()


def read_fact_time(
    path: Path,
    target_date: date,
) -> list[dict[str, str]]:
    """Read and validate a single Fact_Time dataset."""
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        validate_fact_time_columns(
            reader.fieldnames,
            path,
        )

        rows = list(reader)

    target_date_string = target_date.isoformat()
    filtered_rows: list[dict[str, str]] = []

    for row in rows:
        row_date = normalize_dimension(row.get("Date"))

        if row_date != target_date_string:
            raise ValueError(
                f"Fact_Time file contains unexpected date "
                f"'{row_date}' while processing "
                f"{target_date_string}.\n"
                f"File: {path}"
            )

        filtered_rows.append(row)

    return filtered_rows


def aggregate_daily_rows(
    fact_rows: list[dict[str, str]],
    target_date: date,
) -> list[dict[str, str]]:
    """Aggregate Fact_Time rows into Daily_Time rows."""
    totals: dict[tuple[str, str], float] = defaultdict(float)
    event_counts: dict[tuple[str, str], int] = defaultdict(int)

    for row in fact_rows:
        category = normalize_dimension(row.get("Category"))
        subcategory = normalize_dimension(row.get("Subcategory"))
        duration = parse_duration(
            row.get("Duration_sec", ""),
            Path("<Fact_Time input>"),
        )

        key = (category, subcategory)

        totals[key] += duration
        event_counts[key] += 1

    daily_rows: list[dict[str, str]] = []

    for (category, subcategory), duration in sorted(
        totals.items(),
        key=lambda item: (
            item[0][0],
            item[0][1],
        ),
    ):
        daily_rows.append(
            {
                "Date": target_date.isoformat(),
                "Category": category,
                "Subcategory": subcategory,
                "Duration_sec": f"{duration:.3f}",
                "Duration_min": f"{duration / 60:.3f}",
                "Duration_hours": f"{duration / 3600:.6f}",
                "Event_Count": str(event_counts[(category, subcategory)]),
            }
        )

    return daily_rows


def write_daily_time(
    path: Path,
    rows: list[dict[str, str]],
) -> None:
    """Write a deterministic Daily_Time CSV."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(".tmp")

    with temporary_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=DAILY_TIME_COLUMNS,
            extrasaction="raise",
        )

        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(path)


def calculate_duration(
    rows: list[dict[str, str]],
) -> float:
    """Calculate total Daily_Time duration."""
    return sum(
        float(row["Duration_sec"])
        for row in rows
    )


def format_duration(seconds: float) -> str:
    """Format seconds as hours and minutes."""
    total_minutes = int(
        round(max(seconds, 0.0) / 60)
    )

    hours, minutes = divmod(
        total_minutes,
        60,
    )

    return f"{hours}h {minutes:02d}m"


def build_date(
    source: SourceDefinition,
    target_date: date,
) -> tuple[int, float, bool]:
    """Build Daily_Time for one date."""
    ensure_generic_build_allowed(source)

    fact_path = get_fact_time_path(
        source,
        target_date,
    )

    daily_path = get_daily_time_path(
        source,
        target_date,
    )

    print(f"--- {target_date.isoformat()} ---")
    print(f"Fact_Time input : {fact_path}")
    print(f"Daily_Time output: {daily_path}")

    if not fact_path.exists():
        print("Fact_Time rows   : MISSING")
        print("Daily_Time rows  : 0")
        print("RESULT           : MISSING INPUT")
        print()

        return 0, 0.0, False

    fact_rows = read_fact_time(
        fact_path,
        target_date,
    )

    if not fact_rows:
        write_daily_time(
            daily_path,
            [],
        )

        print("Fact_Time rows   : 0")
        print("Daily_Time rows  : 0")
        print("Total daily time : 0m")
        print("RESULT           : ZERO-EVENT DATE")
        print()

        return 0, 0.0, True

    daily_rows = aggregate_daily_rows(
        fact_rows,
        target_date,
    )

    write_daily_time(
        daily_path,
        daily_rows,
    )

    total_duration = calculate_duration(
        daily_rows
    )

    print(
        f"Fact_Time rows   : {len(fact_rows):,}"
    )
    print(
        f"Daily_Time rows  : {len(daily_rows):,}"
    )
    print(
        f"Total daily time : {format_duration(total_duration)}"
    )
    print(
        f"Output           : {daily_path}"
    )
    print("RESULT           : BUILT")
    print()

    return (
        len(daily_rows),
        total_duration,
        True,
    )


def main() -> int:
    """Build Daily_Time datasets for the requested source and dates."""
    args = parse_arguments()

    try:
        source = get_source_definition(
            args.source
        )

        ensure_generic_build_allowed(source)

        start_date, end_date = parse_date_range(args)

        for target_date in get_date_range(
            start_date,
            end_date,
        ):
            validate_completed_date(target_date)

        print("# Daily_Time Builder")
        print()
        print(f"Source   : {args.source}")
        print(f"Context  : {source.context}")
        print(
            f"Device   : "
            f"{source.device or 'None'}"
        )
        print(
            f"Timezone : {DEFAULT_TIMEZONE}"
        )
        print(
            f"Dates    : "
            f"{start_date.isoformat()} → "
            f"{end_date.isoformat()}"
        )
        print(
            "Mode     : COMPLETED DAYS ONLY"
        )
        print()

        print("=== Configuration ===")
        print(
            f"Fact input : "
            f"{get_fact_time_directory(source)}"
        )
        print(
            f"Daily output: "
            f"{get_daily_time_directory(source)}"
        )
        print()

        dates_checked = 0
        dates_built = 0
        zero_event_dates = 0
        missing_fact_dates = 0
        total_rows = 0
        total_duration = 0.0

        for target_date in get_date_range(
            start_date,
            end_date,
        ):
            dates_checked += 1

            rows, duration, found = build_date(
                source,
                target_date,
            )

            if not found:
                missing_fact_dates += 1
                continue

            dates_built += 1

            if rows == 0:
                zero_event_dates += 1
                continue

            total_rows += rows
            total_duration += duration

        print("=" * 60)
        print("=== Daily_Time Build Summary ===")
        print(
            f"Dates checked          : {dates_checked}"
        )
        print(
            f"Dates built            : {dates_built}"
        )
        print(
            f"Daily_Time rows        : {total_rows:,}"
        )
        print(
            f"Total daily time       : "
            f"{format_duration(total_duration)}"
        )
        print(
            f"Zero-event dates       : "
            f"{zero_event_dates}"
        )
        print(
            f"Missing Fact_Time dates: "
            f"{missing_fact_dates}"
        )

        if missing_fact_dates:
            print()
            print(
                "RESULT: DAILY_TIME BUILD FAILED."
            )
            print(
                "One or more requested dates do not "
                "have canonical Fact_Time input."
            )
            return 1

        print()
        print(
            "RESULT: DAILY_TIME BUILD PASSED."
        )
        return 0

    except (ValueError, RuntimeError, OSError) as exc:
        print()
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())