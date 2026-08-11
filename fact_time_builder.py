# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\fact_time_builder.py

"""Build Fact_Time datasets from Raw ActivityWatch CSV files.

Fact_Time is the event-level analytical layer between raw ActivityWatch
data and higher-level time summaries.

The builder is idempotent and safe to rerun. Dates with a valid Raw
ActivityWatch file containing zero events receive an empty Fact_Time
dataset with the standard schema. This preserves the distinction between
"known zero activity" and "missing source data".
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from tracker_config import (
    ensure_output_directories,
    fact_time_path,
    latest_completed_date,
    today_local,
    validate_completed_date,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parent

OUTPUT_DIRECTORY = (
    PROJECT_DIRECTORY / "output"
)

RAW_DIRECTORY = OUTPUT_DIRECTORY

FACT_DIRECTORY = (
    OUTPUT_DIRECTORY / "Fact_Time"
)

FACT_TIME_COLUMNS = [
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
]

RAW_REQUIRED_COLUMNS = [
    "ActivityWatch_Event_ID",
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
]


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build Fact_Time datasets from Raw ActivityWatch data."
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
            "Build the specified number of dates ending with "
            "the latest eligible date."
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
        help=(
            "Allow processing today's incomplete data. "
            "Use only when explicitly required."
        ),
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

        first_date = (
            latest_allowed
            - timedelta(days=args.days - 1)
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
                raise ValueError(
                    f"End date {end_date.isoformat()} is the "
                    f"current day or later. Completed days only "
                    f"allows dates through "
                    f"{latest_allowed.isoformat()}."
                )

        return [
            start_date + timedelta(days=offset)
            for offset in range(
                (end_date - start_date).days + 1
            )
        ]

    return [latest_allowed]


def raw_activitywatch_path(
    target_date: date,
) -> Path:
    """Return the Raw ActivityWatch CSV path."""
    return (
        RAW_DIRECTORY
        / f"Raw_ActivityWatch_{target_date.isoformat()}.csv"
    )


def read_csv(
    path: Path,
) -> list[dict[str, str]]:
    """Read a CSV file."""
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


def validate_raw_schema(
    path: Path,
    fieldnames: list[str] | None,
) -> None:
    """Validate the Raw ActivityWatch CSV schema."""
    if fieldnames is None:
        raise ValueError(
            f"CSV has no header: {path}"
        )

    missing = [
        column
        for column in RAW_REQUIRED_COLUMNS
        if column not in fieldnames
    ]

    if missing:
        raise ValueError(
            f"Raw ActivityWatch file is missing required "
            f"columns: {missing}\n"
            f"File: {path}"
        )


def read_raw_activitywatch(
    path: Path,
) -> list[dict[str, str]]:
    """Read a Raw ActivityWatch CSV.

    Empty Raw datasets are valid because they represent a date that was
    successfully checked in ActivityWatch but contained no events.
    """
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

        rows = list(reader)

        if not rows:
            return []

        validate_raw_schema(
            path,
            reader.fieldnames,
        )

        return rows
    
def normalize_text(
    value: Any,
) -> str:
    """Normalize a CSV value to a trimmed string."""
    if value is None:
        return ""

    return str(value).strip()


def parse_duration(
    value: str,
    path: Path,
    row_number: int,
) -> float:
    """Parse and validate an event duration."""
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
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


def build_fact_time_id(
    target_date: date,
    source_event_id: str,
    start: str,
    end: str,
) -> str:
    """Create a deterministic Fact_Time identifier."""
    source = "|".join(
        [
            target_date.isoformat(),
            source_event_id,
            start,
            end,
        ]
    )

    digest = hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()[:20]

    return f"FT_{digest}"


def normalize_raw_event(
    row: dict[str, str],
    target_date: date,
    path: Path,
    row_number: int,
) -> dict[str, Any]:
    """Convert one Raw ActivityWatch row into a Fact_Time row."""
    row_date = normalize_text(
        row.get("Date")
    )

    expected_date = target_date.isoformat()

    if row_date != expected_date:
        raise ValueError(
            f"Date mismatch in {path}, row {row_number}: "
            f"found '{row_date}', expected '{expected_date}'."
        )

    source_event_id = normalize_text(
        row.get("Source_Event_ID")
    )

    if not source_event_id:
        source_event_id = normalize_text(
            row.get("ActivityWatch_Event_ID")
        )

    if not source_event_id:
        raise ValueError(
            f"Missing source event ID in {path}, "
            f"row {row_number}."
        )

    start = normalize_text(
        row.get("Start")
    )

    end = normalize_text(
        row.get("End")
    )

    duration = parse_duration(
        normalize_text(
            row.get("Duration_sec")
        ),
        path,
        row_number,
    )

    category = (
        normalize_text(
            row.get("Category")
        )
        or "Uncategorized"
    )

    subcategory = normalize_text(
        row.get("Subcategory")
    )

    fact_time_id = build_fact_time_id(
        target_date=target_date,
        source_event_id=source_event_id,
        start=start,
        end=end,
    )

    return {
        "Fact_Time_ID": fact_time_id,
        "Date": expected_date,
        "Start": start,
        "End": end,
        "Duration_sec": round(
            duration,
            3,
        ),
        "Device": normalize_text(
            row.get("Device")
        ),
        "Source": (
            normalize_text(
                row.get("Source")
            )
            or "ActivityWatch"
        ),
        "Source_Bucket": normalize_text(
            row.get("Source_Bucket")
        ),
        "Source_Event_ID": source_event_id,
        "App": normalize_text(
            row.get("App")
        ),
        "Window_Title": normalize_text(
            row.get("Window_Title")
        ),
        "Category": category,
        "Subcategory": subcategory,
    }


def normalize_events(
    rows: list[dict[str, str]],
    target_date: date,
    path: Path,
) -> tuple[
    list[dict[str, Any]],
    int,
]:
    """Normalize raw rows and remove duplicate source events."""
    normalized: list[dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    duplicate_count = 0

    for row_number, row in enumerate(
        rows,
        start=2,
    ):
        source_event_id = normalize_text(
            row.get("Source_Event_ID")
        )

        if not source_event_id:
            source_event_id = normalize_text(
                row.get("ActivityWatch_Event_ID")
            )

        if source_event_id in seen_source_ids:
            duplicate_count += 1
            continue

        seen_source_ids.add(
            source_event_id
        )

        normalized.append(
            normalize_raw_event(
                row=row,
                target_date=target_date,
                path=path,
                row_number=row_number,
            )
        )

    normalized.sort(
        key=lambda row: (
            row["Start"],
            row["Source_Event_ID"],
        )
    )

    return normalized, duplicate_count


def write_csv_atomic(
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write a CSV atomically."""
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
                fieldnames=FACT_TIME_COLUMNS,
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


def read_existing_fact_time(
    path: Path,
) -> list[dict[str, str]]:
    """Read an existing Fact_Time file."""
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
                f"Fact_Time CSV has no header: {path}"
            )

        missing = [
            column
            for column in FACT_TIME_COLUMNS
            if column not in reader.fieldnames
        ]

        if missing:
            raise ValueError(
                f"Fact_Time file is missing required "
                f"columns: {missing}\n"
                f"File: {path}"
            )

        return list(reader)


def merge_fact_time_rows(
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    int,
    int,
]:
    """Merge new facts with existing facts by source event."""
    existing_by_source_id: dict[
        str,
        dict[str, str],
    ] = {}

    for row in existing_rows:
        source_event_id = normalize_text(
            row.get("Source_Event_ID")
        )

        if source_event_id:
            existing_by_source_id[
                source_event_id
            ] = row

    already_present = 0
    new_count = 0

    for row in new_rows:
        source_event_id = normalize_text(
            row.get("Source_Event_ID")
        )

        if source_event_id in existing_by_source_id:
            already_present += 1
            continue

        existing_by_source_id[
            source_event_id
        ] = {
            column: row.get(column, "")
            for column in FACT_TIME_COLUMNS
        }

        new_count += 1

    final_rows = list(
        existing_by_source_id.values()
    )

    final_rows.sort(
        key=lambda row: (
            str(row.get("Start", "")),
            str(row.get("Source_Event_ID", "")),
        )
    )

    return (
        final_rows,
        already_present,
        new_count,
    )


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


def total_duration(
    rows: list[dict[str, Any]],
) -> float:
    """Calculate total event duration."""
    total = 0.0

    for row in rows:
        value = row.get(
            "Duration_sec",
            0,
        )

        try:
            total += float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid Duration_sec in Fact_Time data: "
                f"'{value}'."
            )

    return total


def process_date(
    target_date: date,
) -> dict[str, Any]:
    """Build Fact_Time for one date."""
    print()
    print(
        f"--- {target_date.isoformat()} ---"
    )

    raw_path = raw_activitywatch_path(
        target_date
    )

    output_path = fact_time_path(
        target_date
    )

    print(
        f"Raw ActivityWatch : {raw_path}"
    )

    print(
        f"Fact_Time output  : {output_path}"
    )

    if not raw_path.exists():
        print(
            "Result: Raw ActivityWatch file not found."
        )

        return {
            "date": target_date,
            "status": "missing_raw",
            "raw_rows": 0,
            "unique_source_events": 0,
            "duplicate_source_events": 0,
            "existing_rows": (
                len(read_existing_fact_time(output_path))
                if output_path.exists()
                else 0
            ),
            "already_present": 0,
            "new_rows": 0,
            "final_rows": 0,
            "duration": 0.0,
            "output": output_path,
        }

    raw_rows = read_raw_activitywatch(
        raw_path
    )

    print(
        f"Raw ActivityWatch rows : {len(raw_rows):,}"
    )

    existing_rows = read_existing_fact_time(
        output_path
    )

    print(
        f"Existing Fact_Time rows : "
        f"{len(existing_rows):,}"
    )

    # A valid empty Raw dataset is meaningful: ActivityWatch
    # confirms that the date was checked and contained no events.
    if not raw_rows:

        write_csv_atomic(
        rows=[],
        path=output_path,
    )

    print(
        "Result: Raw ActivityWatch contains "
        "0 events."
    )

    print(
        "Created empty Fact_Time dataset "
        "with standard schema."
    )

    print(
        "Final Fact_Time rows    : 0"
    )

    print(
        "Total fact time         : 0m"
    )

    print(
        f"Output                  : {output_path}"
    )

    return {
        "date": target_date,
        "status": "zero_events",
        "raw_rows": 0,
        "unique_source_events": 0,
        "duplicate_source_events": 0,
        "existing_rows": len(existing_rows),
        "already_present": 0,
        "new_rows": 0,
        "final_rows": 0,
        "duration": 0.0,
        "output": output_path,
    }
    normalized_rows, duplicate_count = (
        normalize_events(
            rows=raw_rows,
            target_date=target_date,
            path=raw_path,
        )
    )

    print(
        f"Unique source events   : "
        f"{len(normalized_rows):,}"
    )

    print(
        f"Duplicate source events: "
        f"{duplicate_count:,}"
    )

    (
        final_rows,
        already_present,
        new_count,
    ) = merge_fact_time_rows(
        existing_rows=existing_rows,
        new_rows=normalized_rows,
    )

    write_csv_atomic(
        rows=final_rows,
        path=output_path,
    )

    duration = total_duration(
        final_rows
    )

    print(
        f"Already present         : "
        f"{already_present:,}"
    )

    print(
        f"New facts added         : "
        f"{new_count:,}"
    )

    print(
        f"Final Fact_Time rows    : "
        f"{len(final_rows):,}"
    )

    print(
        f"Total fact time         : "
        f"{format_duration(duration)}"
    )

    print(
        f"Output                  : {output_path}"
    )

    return {
        "date": target_date,
        "status": "updated",
        "raw_rows": len(raw_rows),
        "unique_source_events": len(normalized_rows),
        "duplicate_source_events": duplicate_count,
        "existing_rows": len(existing_rows),
        "already_present": already_present,
        "new_rows": new_count,
        "final_rows": len(final_rows),
        "duration": duration,
        "output": output_path,
    }


def main() -> int:
    """Build Fact_Time datasets."""
    try:
        args = parse_arguments()

        ensure_output_directories()
        FACT_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
        )

        dates = resolve_target_dates(
            args
        )

        first_date = dates[0]
        last_date = dates[-1]

        print("# Fact_Time Builder")
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
            f"Raw input : {RAW_DIRECTORY}"
        )
        print(
            f"Fact output: {FACT_DIRECTORY}"
        )

        results: list[dict[str, Any]] = []

        for target_date in dates:
            results.append(
                process_date(
                    target_date
                )
            )

        updated = [
            result
            for result in results
            if result["status"] == "updated"
        ]

        zero_events = [
            result
            for result in results
            if result["status"] == "zero_events"
        ]

        missing_raw = [
            result
            for result in results
            if result["status"] == "missing_raw"
        ]

        total_new = sum(
            int(result["new_rows"])
            for result in results
        )

        total_final_rows = sum(
            int(result["final_rows"])
            for result in results
        )

        total_duration_seconds = sum(
            float(result["duration"])
            for result in results
        )

        print()
        print(
            "=" * 60
        )
        print(
            "=== Fact_Time Build Summary ==="
        )

        print(
            f"Dates requested       : "
            f"{len(results):,}"
        )

        print(
            f"Datasets updated      : "
            f"{len(updated):,}"
        )

        print(
            f"Zero-event datasets   : "
            f"{len(zero_events):,}"
        )

        print(
            f"Missing Raw datasets  : "
            f"{len(missing_raw):,}"
        )

        print(
            f"New facts added       : "
            f"{total_new:,}"
        )

        print(
            f"Final Fact_Time rows  : "
            f"{total_final_rows:,}"
        )

        print(
            f"Total fact time       : "
            f"{format_duration(total_duration_seconds)}"
        )

        if zero_events:
            print()
            print(
                "Zero-event dates:"
            )

            for result in zero_events:
                print(
                    f"  - "
                    f"{result['date'].isoformat()}"
                )

        if missing_raw:
            print()
            print(
                "Missing Raw ActivityWatch dates:"
            )

            for result in missing_raw:
                print(
                    f"  - "
                    f"{result['date'].isoformat()}"
                )

        if missing_raw:
            print()
            print(
                "RESULT: Fact_Time build completed with "
                "missing Raw ActivityWatch datasets."
            )
            return 1

        print()
        print(
            "RESULT: Fact_Time datasets were "
            "built successfully."
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