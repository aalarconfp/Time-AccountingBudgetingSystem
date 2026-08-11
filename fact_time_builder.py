# G:\My Drive\Personal Life\Habit and Wellness\System_Tracker\fact_time_builder.py

"""Build the canonical Fact_Time layer from source-specific Raw datasets.

Fact_Time is a normalized event-level layer. It preserves the source event
identity while providing stable field names for downstream Daily_Time and
analysis layers.

Existing Fact_Time records are reconciled against the current Raw source.
This is intentionally an upsert rather than an append-only operation because
source-derived attributes such as taxonomy may be corrected after an event
was originally ingested.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config.paths import get_source_raw_root
from config.sources import (
    SourceDefinition,
    SourceType,
    get_source_definition,
)
from config.tracker_config import DEFAULT_TIMEZONE


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


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build canonical Fact_Time records from Raw datasets."
        )
    )

    parser.add_argument(
        "--date",
        dest="target_date",
        help=(
            "Calendar date to build in YYYY-MM-DD format. "
            "Defaults to today in the project timezone."
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
            "Configured source. Default: asus_laptop."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Project output directory override."
        ),
    )

    return parser.parse_args()


def get_project_timezone() -> ZoneInfo:
    """Return the configured project timezone."""
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load project timezone "
            f"'{DEFAULT_TIMEZONE}'."
        ) from exc


def parse_target_date(
    value: str | None,
) -> date:
    """Parse the requested date."""
    timezone = get_project_timezone()

    if value is None:
        return datetime.now(timezone).date()

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. "
            "Expected YYYY-MM-DD."
        ) from exc


def latest_completed_date() -> date:
    """Return the latest completed project-local calendar date."""
    return (
        datetime.now(get_project_timezone()).date()
        - timedelta(days=1)
    )


def validate_completed_date(
    target_date: date,
) -> None:
    """Reject dates that have not yet completed."""
    latest_date = latest_completed_date()

    if target_date > latest_date:
        raise ValueError(
            f"Date {target_date.isoformat()} is not a "
            f"completed day. Latest completed date is "
            f"{latest_date.isoformat()}."
        )


def get_source_date_range(
    target_date: date,
) -> tuple[date, date]:
    """Return the requested date range."""
    return target_date, target_date


def get_raw_root(
    source: SourceDefinition,
) -> Path:
    """Return the canonical Raw root for the source."""
    return get_source_raw_root(
        source.source
    )


def get_source_device(
    source: SourceDefinition,
) -> str:
    """Return the configured device for the source."""
    if source.device is None:
        raise ValueError(
            f"Source '{source.source.value}' has no device."
        )

    return source.device


def get_raw_file_path(
    source: SourceDefinition,
    target_date: date,
    output_directory_override: Path | None,
) -> Path:
    """Return the canonical Raw input path."""
    device = get_source_device(source)

    filename = (
        f"Raw_ActivityWatch_"
        f"{target_date.isoformat()}.csv"
    )

    if output_directory_override is not None:
        return (
            output_directory_override
            / "Raw"
            / "ActivityWatch"
            / device
            / filename
        )

    return (
        get_raw_root(source)
        / device
        / filename
    )


def get_fact_root(
    source: SourceDefinition,
    output_directory_override: Path | None,
) -> Path:
    """Return the canonical Fact_Time output root."""
    device = get_source_device(source)

    if output_directory_override is not None:
        return (
            output_directory_override
            / "Fact"
            / "Time"
            / "ActivityWatch"
            / device
        )

    project_root = (
        get_raw_root(source)
        .parents[1]
    )

    return (
        project_root
        / "Fact"
        / "Time"
        / "ActivityWatch"
        / device
    )


def get_fact_file_path(
    source: SourceDefinition,
    target_date: date,
    output_directory_override: Path | None,
) -> Path:
    """Return the canonical Fact_Time output path."""
    return (
        get_fact_root(
            source=source,
            output_directory_override=output_directory_override,
        )
        / (
            f"Fact_Time_"
            f"{target_date.isoformat()}.csv"
        )
    )


def read_csv(
    path: Path,
) -> list[dict[str, str]]:
    """Read a CSV file as dictionaries."""
    if not path.exists():
        return []

    with path.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        return list(
            csv.DictReader(file)
        )


def write_csv(
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write rows to a UTF-8 CSV file."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        ".tmp"
    )

    with temporary_path.open(
        mode="w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FACT_TIME_COLUMNS,
            extrasaction="raise",
        )

        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(path)


def normalize_text(
    value: Any,
) -> str:
    """Normalize a value into a stable string."""
    if value is None:
        return ""

    return str(value).strip()


def normalize_duration(
    value: Any,
) -> float:
    """Normalize duration into seconds."""
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid Duration_sec value: {value!r}."
        ) from exc

    if seconds < 0:
        raise ValueError(
            f"Duration_sec cannot be negative: {seconds}."
        )

    return round(seconds, 3)


def build_fact_time_id(
    device: str,
    source_event_id: str,
) -> str:
    """Build a deterministic Fact_Time identifier."""
    return (
        f"{device}:"
        f"ActivityWatch:"
        f"{source_event_id}"
    )


def raw_to_fact(
    raw_row: dict[str, str],
    device: str,
) -> dict[str, Any]:
    """Convert one Raw ActivityWatch event into Fact_Time."""
    source_event_id = normalize_text(
        raw_row.get("AW_Event_ID")
    )

    if not source_event_id:
        raise ValueError(
            "Raw ActivityWatch event has no AW_Event_ID."
        )

    category = normalize_text(
        raw_row.get("AW_Category")
    )

    subcategory = normalize_text(
        raw_row.get("AW_Subcategory")
    )

    return {
        "Fact_Time_ID": build_fact_time_id(
            device=device,
            source_event_id=source_event_id,
        ),
        "Date": normalize_text(
            raw_row.get("Date")
        ),
        "Start": normalize_text(
            raw_row.get("Start")
        ),
        "End": normalize_text(
            raw_row.get("End")
        ),
        "Duration_sec": normalize_duration(
            raw_row.get("Duration_sec")
        ),
        "Device": normalize_text(
            raw_row.get("Device")
        ) or device,
        "Source": normalize_text(
            raw_row.get("Source")
        ),
        "Source_Bucket": normalize_text(
            raw_row.get("Bucket")
        ),
        "Source_Event_ID": source_event_id,
        "App": normalize_text(
            raw_row.get("App")
        ),
        "Window_Title": (
            normalize_text(
                raw_row.get("Title")
            )
            or normalize_text(
                raw_row.get("Window_Title")
            )
        ),
        "Category": category,
        "Subcategory": subcategory,
    }


def fact_identity(
    row: dict[str, Any],
) -> str:
    """Return the stable source-event identity."""
    return normalize_text(
        row.get("Source_Event_ID")
    )


def comparable_fact(
    row: dict[str, Any],
) -> tuple[str, ...]:
    """Return source-derived fields used for reconciliation."""
    return tuple(
        normalize_text(
            row.get(column)
        )
        for column in FACT_TIME_COLUMNS
        if column != "Fact_Time_ID"
    )


def deduplicate_raw_rows(
    raw_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    """Deduplicate Raw rows by ActivityWatch event ID."""
    unique: dict[str, dict[str, str]] = {}
    duplicate_count = 0

    for row in raw_rows:
        event_id = normalize_text(
            row.get("AW_Event_ID")
        )

        if not event_id:
            raise ValueError(
                "Raw ActivityWatch dataset contains "
                "an event without AW_Event_ID."
            )

        if event_id in unique:
            duplicate_count += 1
            continue

        unique[event_id] = row

    rows = list(
        unique.values()
    )

    rows.sort(
        key=lambda row: (
            normalize_text(
                row.get("Start")
            ),
            normalize_text(
                row.get("AW_Event_ID")
            ),
        )
    )

    return rows, duplicate_count


def reconcile_date(
    raw_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
    device: str,
) -> tuple[
    list[dict[str, Any]],
    int,
    int,
    int,
]:
    """Reconcile Raw records with existing Fact_Time records."""
    deduplicated_raw, duplicate_count = (
        deduplicate_raw_rows(raw_rows)
    )

    existing_by_event: dict[str, dict[str, str]] = {}

    for row in existing_rows:
        event_id = fact_identity(row)

        if not event_id:
            continue

        existing_by_event[event_id] = row

    reconciled: list[dict[str, Any]] = []

    new_count = 0
    updated_count = 0
    unchanged_count = 0

    for raw_row in deduplicated_raw:
        fact_row = raw_to_fact(
            raw_row=raw_row,
            device=device,
        )

        event_id = fact_identity(
            fact_row
        )

        existing = existing_by_event.get(
            event_id
        )

        if existing is None:
            new_count += 1
            reconciled.append(
                fact_row
            )
            continue

        existing_normalized = raw_to_fact(
            raw_row={
                "AW_Event_ID": existing.get(
                    "Source_Event_ID",
                    "",
                ),
                "Date": existing.get(
                    "Date",
                    "",
                ),
                "Start": existing.get(
                    "Start",
                    "",
                ),
                "End": existing.get(
                    "End",
                    "",
                ),
                "Duration_sec": existing.get(
                    "Duration_sec",
                    "0",
                ),
                "Device": existing.get(
                    "Device",
                    "",
                ),
                "Source": existing.get(
                    "Source",
                    "",
                ),
                "Bucket": existing.get(
                    "Source_Bucket",
                    "",
                ),
                "App": existing.get(
                    "App",
                    "",
                ),
                "Title": existing.get(
                    "Window_Title",
                    "",
                ),
                "AW_Category": existing.get(
                    "Category",
                    "",
                ),
                "AW_Subcategory": existing.get(
                    "Subcategory",
                    "",
                ),
            },
            device=device,
        )

        if comparable_fact(
            existing_normalized
        ) == comparable_fact(
            fact_row
        ):
            unchanged_count += 1
            reconciled.append(
                {
                    column: (
                        existing.get(
                            column,
                            "",
                        )
                        if column == "Fact_Time_ID"
                        else fact_row[column]
                    )
                    for column in FACT_TIME_COLUMNS
                }
            )
        else:
            updated_count += 1
            reconciled.append(
                fact_row
            )

    reconciled.sort(
        key=lambda row: (
            normalize_text(
                row["Start"]
            ),
            normalize_text(
                row["Source_Event_ID"]
            ),
        )
    )

    return (
        reconciled,
        duplicate_count,
        new_count,
        updated_count,
        unchanged_count,
    )


def calculate_duration(
    rows: list[dict[str, Any]],
) -> float:
    """Calculate total Fact_Time duration."""
    return sum(
        float(
            row["Duration_sec"]
        )
        for row in rows
    )


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


def print_date_summary(
    target_date: date,
    raw_path: Path,
    fact_path: Path,
    raw_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
    final_rows: list[dict[str, Any]],
    duplicate_count: int,
    new_count: int,
    updated_count: int,
    unchanged_count: int,
) -> None:
    """Print the reconciliation summary for one date."""
    print()
    print(
        f"--- {target_date.isoformat()} ---"
    )
    print(
        f"Raw ActivityWatch : {raw_path}"
    )
    print(
        f"Fact_Time output  : {fact_path}"
    )
    print(
        f"Raw ActivityWatch rows : "
        f"{len(raw_rows)}"
    )
    print(
        f"Existing Fact_Time rows: "
        f"{len(existing_rows)}"
    )
    print(
        f"Unique ActivityWatch IDs : "
        f"{len(final_rows)}"
    )
    print(
        f"Duplicate IDs removed    : "
        f"{duplicate_count}"
    )
    print(
        f"Already in Fact_Time     : "
        f"{unchanged_count}"
    )
    print(
        f"New facts added          : "
        f"{new_count}"
    )
    print(
        f"Updated facts            : "
        f"{updated_count}"
    )
    print(
        f"Final Fact_Time rows     : "
        f"{len(final_rows)}"
    )
    print(
        f"Total fact time          : "
        f"{format_duration(calculate_duration(final_rows))}"
    )
    print(
        f"Output                   : "
        f"{fact_path}"
    )


def main() -> int:
    """Run the Fact_Time builder."""
    args = parse_arguments()

    try:
        source = get_source_definition(
            args.source
        )

        if source.source is not SourceType.ACTIVITYWATCH:
            raise ValueError(
                f"Source '{args.source}' is not "
                "an ActivityWatch source."
            )

        device = get_source_device(
            source
        )

        target_date = parse_target_date(
            args.target_date
        )

        validate_completed_date(
            target_date
        )

        start_date, end_date = (
            get_source_date_range(
                target_date
            )
        )

        print("# Fact_Time Builder")
        print()
        print(
            f"Source   : {args.source}"
        )
        print(
            f"Device   : {device}"
        )
        print(
            f"Context  : {source.context}"
        )
        print(
            f"Timezone : {DEFAULT_TIMEZONE}"
        )
        print(
            f"Date     : "
            f"{start_date.isoformat()}"
        )

        if start_date != end_date:
            print(
                f"          → "
                f"{end_date.isoformat()}"
            )

        print(
            "Mode     : COMPLETED DAYS ONLY"
        )

        raw_root = get_raw_root(
            source
        )

        fact_root = get_fact_root(
            source=source,
            output_directory_override=args.output_dir,
        )

        print()
        print("=== Configuration ===")
        print(
            f"Raw input : {raw_root}"
        )
        print(
            f"Fact output: {fact_root}"
        )

        total_new = 0
        total_updated = 0
        total_unchanged = 0
        total_duplicates = 0
        total_rows = 0
        total_seconds = 0.0
        zero_event_dates = 0
        missing_raw_dates = 0

        current_date = start_date

        while current_date <= end_date:
            raw_path = get_raw_file_path(
                source=source,
                target_date=current_date,
                output_directory_override=args.output_dir,
            )

            fact_path = get_fact_file_path(
                source=source,
                target_date=current_date,
                output_directory_override=args.output_dir,
            )

            if not raw_path.exists():
                missing_raw_dates += 1

                print()
                print(
                    f"--- {current_date.isoformat()} ---"
                )
                print(
                    f"Missing Raw ActivityWatch: "
                    f"{raw_path}"
                )

                current_date += timedelta(
                    days=1
                )
                continue

            raw_rows = read_csv(
                raw_path
            )

            existing_rows = read_csv(
                fact_path
            )

            if not raw_rows:
                zero_event_dates += 1

            (
                final_rows,
                duplicate_count,
                new_count,
                updated_count,
                unchanged_count,
            ) = reconcile_date(
                raw_rows=raw_rows,
                existing_rows=existing_rows,
                device=device,
            )

            write_csv(
                rows=final_rows,
                path=fact_path,
            )

            print_date_summary(
                target_date=current_date,
                raw_path=raw_path,
                fact_path=fact_path,
                raw_rows=raw_rows,
                existing_rows=existing_rows,
                final_rows=final_rows,
                duplicate_count=duplicate_count,
                new_count=new_count,
                updated_count=updated_count,
                unchanged_count=unchanged_count,
            )

            total_new += new_count
            total_updated += updated_count
            total_unchanged += unchanged_count
            total_duplicates += duplicate_count
            total_rows += len(final_rows)
            total_seconds += calculate_duration(
                final_rows
            )

            current_date += timedelta(
                days=1
            )

        print()
        print("=" * 60)
        print("=== Fact_Time Build Summary ===")
        print(
            f"Dates checked          : "
            f"{(
                end_date - start_date
            ).days + 1}"
        )
        print(
            f"New facts added        : "
            f"{total_new:,}"
        )
        print(
            f"Updated facts          : "
            f"{total_updated:,}"
        )
        print(
            f"Unchanged facts        : "
            f"{total_unchanged:,}"
        )
        print(
            f"Duplicate IDs removed  : "
            f"{total_duplicates:,}"
        )
        print(
            f"Final Fact_Time rows   : "
            f"{total_rows:,}"
        )
        print(
            f"Total fact time        : "
            f"{format_duration(total_seconds)}"
        )
        print(
            f"Zero-event dates       : "
            f"{zero_event_dates}"
        )
        print(
            f"Missing Raw dates      : "
            f"{missing_raw_dates}"
        )

        if missing_raw_dates:
            print()
            print(
                "RESULT: FACT_TIME BUILD FAILED."
            )
            return 1

        print()
        print(
            "RESULT: FACT_TIME BUILD PASSED."
        )

        return 0

    except (
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        print()
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())