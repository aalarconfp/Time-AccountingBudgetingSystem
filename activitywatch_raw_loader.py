# activitywatch_raw_loader.py

"""Incrementally load ActivityWatch canonical events into Raw_ActivityWatch.

The loader reads ActivityWatch without modifying the ActivityWatch server.

Default behavior processes completed calendar days only. The current local
calendar day is excluded unless --include-today is explicitly supplied.

Canonical output is stored under:

    output/Raw/ActivityWatch/<device>/Raw_ActivityWatch_<date>.csv

Examples:

    python activitywatch_raw_loader.py
        Load yesterday.

    python activitywatch_raw_loader.py --days 7
        Load the previous seven completed days.

    python activitywatch_raw_loader.py --date 2026-08-09
        Load one completed date.

    python activitywatch_raw_loader.py \
        --start-date 2026-08-01 \
        --end-date 2026-08-09
        Load an inclusive completed-date range.

    python activitywatch_raw_loader.py --include-today
        Explicitly load today's incomplete data.

    python activitywatch_raw_loader.py \
        --date 2026-08-10 \
        --include-today
        Explicitly load today's incomplete data.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from aw_client import ActivityWatchClient
from aw_client.queries import DesktopQueryParams, canonicalEvents

from config.paths import get_activitywatch_raw_path


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5600

CLIENT_NAME = "system-tracker-raw-loader"

WINDOW_BUCKET_TYPE = "currentwindow"
AFK_BUCKET_TYPE = "afkstatus"

CSV_COLUMNS = [
    "Date",
    "Start",
    "End",
    "Duration_sec",
    "Device",
    "Source",
    "Bucket",
    "AW_Event_ID",
    "App",
    "Window_Title",
    "AW_Category",
    "AW_Subcategory",
]

REQUIRED_COLUMNS = set(CSV_COLUMNS)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Incrementally load ActivityWatch canonical events "
            "into the Raw_ActivityWatch dataset."
        )
    )

    date_group = parser.add_mutually_exclusive_group()

    date_group.add_argument(
        "--date",
        dest="target_date",
        help="Load one calendar date in YYYY-MM-DD format.",
    )

    date_group.add_argument(
        "--days",
        type=int,
        help=(
            "Load this many completed calendar days ending "
            "yesterday. Example: --days 7."
        ),
    )

    date_group.add_argument(
        "--start-date",
        dest="start_date",
        help=(
            "Start of an inclusive date range. "
            "Must be used together with --end-date."
        ),
    )

    parser.add_argument(
        "--end-date",
        dest="end_date",
        help=(
            "End of an inclusive date range. "
            "Must be used together with --start-date."
        ),
    )

    parser.add_argument(
        "--include-today",
        action="store_true",
        help=(
            "Explicitly allow the current local calendar day "
            "to be collected. Without this flag, today is excluded."
        ),
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"ActivityWatch server host. Default: {DEFAULT_HOST}",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"ActivityWatch server port. Default: {DEFAULT_PORT}",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Optional legacy/custom output directory override. "
            "By default the canonical device-specific path is used."
        ),
    )

    return parser.parse_args()


def get_today() -> date:
    """Return today's local calendar date."""
    return datetime.now().astimezone().date()


def get_last_completed_date() -> date:
    """Return yesterday's local calendar date."""
    return get_today() - timedelta(days=1)


def parse_date(
    value: str,
    argument_name: str,
) -> date:
    """Parse a YYYY-MM-DD command-line date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {argument_name} '{value}'. "
            "Expected YYYY-MM-DD."
        ) from exc


def resolve_target_dates(
    args: argparse.Namespace,
) -> list[date]:
    """Resolve command-line arguments into an ordered date list."""
    today = get_today()

    latest_allowed_date = (
        today
        if args.include_today
        else today - timedelta(days=1)
    )

    if args.target_date is not None:
        target_date = parse_date(
            args.target_date,
            "--date",
        )

        if target_date > latest_allowed_date:
            raise ValueError(
                f"{target_date} is the current day and is excluded "
                "by default. Use --include-today if you explicitly "
                "want to collect today's incomplete data."
            )

        return [target_date]

    if args.days is not None:
        if args.days < 1:
            raise ValueError("--days must be at least 1.")

        start = latest_allowed_date - timedelta(
            days=args.days - 1
        )

        return [
            start + timedelta(days=offset)
            for offset in range(args.days)
        ]

    if args.start_date is not None:
        if args.end_date is None:
            raise ValueError(
                "--start-date requires --end-date."
            )

        start = parse_date(
            args.start_date,
            "--start-date",
        )

        end = parse_date(
            args.end_date,
            "--end-date",
        )

        if end < start:
            raise ValueError(
                "--end-date cannot be earlier than --start-date."
            )

        if end > latest_allowed_date:
            if args.include_today:
                end = latest_allowed_date
            else:
                print(
                    f"WARNING: Requested end date {end} includes "
                    f"today or a future date. Limiting range to "
                    f"{latest_allowed_date}."
                )
                end = latest_allowed_date

        if start > end:
            raise ValueError(
                "No eligible dates remain after applying the "
                "completed-day rule."
            )

        number_of_days = (end - start).days + 1

        return [
            start + timedelta(days=offset)
            for offset in range(number_of_days)
        ]

    return [latest_allowed_date]


def get_local_day(
    target_date: date,
) -> tuple[datetime, datetime]:
    """Return timezone-aware local-day boundaries."""
    local_timezone = datetime.now().astimezone().tzinfo

    if local_timezone is None:
        raise RuntimeError(
            "Could not determine the computer's local timezone."
        )

    start = datetime.combine(
        target_date,
        datetime.min.time(),
        tzinfo=local_timezone,
    )

    end = start + timedelta(days=1)

    return start, end


def create_client(
    host: str,
    port: int,
) -> ActivityWatchClient:
    """Create an ActivityWatch API client."""
    return ActivityWatchClient(
        client_name=CLIENT_NAME,
        host=host,
        port=port,
        testing=False,
    )


def get_bucket_ids(
    client: ActivityWatchClient,
) -> tuple[str, str]:
    """Find the ActivityWatch window and AFK buckets."""
    buckets = client.get_buckets()

    window_buckets = [
        bucket_id
        for bucket_id, bucket in buckets.items()
        if bucket.get("type") == WINDOW_BUCKET_TYPE
    ]

    afk_buckets = [
        bucket_id
        for bucket_id, bucket in buckets.items()
        if bucket.get("type") == AFK_BUCKET_TYPE
    ]

    if not window_buckets:
        raise RuntimeError(
            "No currentwindow ActivityWatch bucket was found."
        )

    if not afk_buckets:
        raise RuntimeError(
            "No afkstatus ActivityWatch bucket was found."
        )

    if len(window_buckets) > 1:
        print(
            "WARNING: Multiple window buckets found. "
            f"Using '{window_buckets[0]}'."
        )

    if len(afk_buckets) > 1:
        print(
            "WARNING: Multiple AFK buckets found. "
            f"Using '{afk_buckets[0]}'."
        )

    return window_buckets[0], afk_buckets[0]


def build_canonical_query(
    window_bucket_id: str,
    afk_bucket_id: str,
) -> str:
    """Build the ActivityWatch canonical desktop query."""
    params = DesktopQueryParams(
        bid_window=window_bucket_id,
        bid_afk=afk_bucket_id,
        bid_browsers=[],
        filter_afk=True,
        include_audible=True,
    )

    query = canonicalEvents(params)

    if not query.rstrip().endswith("RETURN = events;"):
        query += "\nRETURN = events;"

    return query


def execute_canonical_query(
    client: ActivityWatchClient,
    query: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Execute the canonical query and validate its response."""
    result = client.query(
        query=query,
        timeperiods=[(start, end)],
        name=CLIENT_NAME,
        cache=False,
    )

    if not result:
        return []

    if len(result) != 1:
        raise RuntimeError(
            "Unexpected ActivityWatch query response: "
            f"expected one result, received {len(result)}."
        )

    events = result[0]

    if not isinstance(events, list):
        raise RuntimeError(
            "Unexpected ActivityWatch query response: "
            f"expected a list, received {type(events).__name__}."
        )

    return events


def parse_event_timestamp(
    event: dict[str, Any],
) -> datetime:
    """Parse an ActivityWatch timestamp into an aware datetime."""
    timestamp = event.get("timestamp")

    if not timestamp:
        raise ValueError(
            f"ActivityWatch event {event.get('id')} "
            "does not contain a timestamp."
        )

    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str):
        parsed = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
    else:
        raise TypeError(
            "Unexpected timestamp type: "
            f"{type(timestamp).__name__}."
        )

    if parsed.tzinfo is None:
        raise ValueError(
            f"ActivityWatch event {event.get('id')} "
            "has a timezone-naive timestamp."
        )

    return parsed


def get_event_duration(
    event: dict[str, Any],
) -> float:
    """Return event duration in seconds."""
    duration = event.get("duration", 0)

    if isinstance(duration, timedelta):
        duration = duration.total_seconds()

    seconds = float(duration)

    if seconds < 0:
        raise ValueError(
            f"ActivityWatch event {event.get('id')} "
            f"has negative duration: {seconds}."
        )

    return seconds


def get_event_data(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Return an event's data dictionary."""
    data = event.get("data", {})

    if not isinstance(data, dict):
        return {}

    return data


def get_category_path(
    data: dict[str, Any],
) -> list[str]:
    """Normalize the ActivityWatch category hierarchy."""
    category = data.get("$category")

    if category is None:
        return []

    if isinstance(category, list):
        return [
            str(value)
            for value in category
            if value is not None
        ]

    return [str(category)]


def format_timestamp(
    timestamp: datetime,
) -> str:
    """Format a local timestamp for CSV storage."""
    return timestamp.astimezone().isoformat(
        timespec="milliseconds"
    )


def normalize_event(
    event: dict[str, Any],
    target_date: date,
    device: str,
    bucket_id: str,
) -> dict[str, Any]:
    """Convert one ActivityWatch event into a raw dataset row."""
    event_id = event.get("id")

    if event_id is None:
        raise ValueError(
            "ActivityWatch event has no ID. "
            "Cannot safely use it as a deduplication key."
        )

    timestamp = parse_event_timestamp(event)
    local_start = timestamp.astimezone()

    duration_seconds = get_event_duration(event)

    local_end = local_start + timedelta(
        seconds=duration_seconds
    )

    data = get_event_data(event)
    category_path = get_category_path(data)

    category = (
        category_path[0]
        if category_path
        else "Uncategorized"
    )

    subcategory = (
        category_path[1]
        if len(category_path) > 1
        else ""
    )

    return {
        "Date": target_date.isoformat(),
        "Start": format_timestamp(local_start),
        "End": format_timestamp(local_end),
        "Duration_sec": round(duration_seconds, 3),
        "Device": device,
        "Source": "ActivityWatch",
        "Bucket": bucket_id,
        "AW_Event_ID": str(event_id),
        "App": str(data.get("app", "")),
        "Window_Title": str(data.get("title", "")),
        "AW_Category": category,
        "AW_Subcategory": subcategory,
    }


def normalize_events(
    events: list[dict[str, Any]],
    target_date: date,
    device: str,
    bucket_id: str,
) -> list[dict[str, Any]]:
    """Normalize ActivityWatch events into CSV rows."""
    rows = [
        normalize_event(
            event=event,
            target_date=target_date,
            device=device,
            bucket_id=bucket_id,
        )
        for event in events
    ]

    rows.sort(
        key=lambda row: (
            row["Start"],
            row["AW_Event_ID"],
        )
    )

    return rows


def deduplicate_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Deduplicate rows by ActivityWatch event ID."""
    unique_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_count = 0

    for row in rows:
        event_id = str(row["AW_Event_ID"])

        if event_id in seen_ids:
            duplicate_count += 1
            continue

        seen_ids.add(event_id)
        unique_rows.append(row)

    return unique_rows, duplicate_count


def get_output_path(
    output_directory: Path | None,
    target_date: date,
    device: str,
) -> Path:
    """Return the deterministic daily raw dataset path."""
    if output_directory is not None:
        return (
            output_directory
            / f"Raw_ActivityWatch_{target_date.isoformat()}.csv"
        )

    return get_activitywatch_raw_path(
        device=device,
        target_date=target_date,
    )


def validate_csv_columns(
    fieldnames: list[str] | None,
    path: Path,
) -> None:
    """Validate the existing raw dataset schema."""
    if fieldnames is None:
        raise ValueError(
            f"CSV file '{path}' has no header."
        )

    actual = set(fieldnames)
    missing = REQUIRED_COLUMNS - actual

    if missing:
        raise ValueError(
            f"CSV file '{path}' is missing required "
            f"columns: {sorted(missing)}"
        )


def read_existing_rows(
    path: Path,
) -> list[dict[str, Any]]:
    """Read an existing Raw_ActivityWatch CSV."""
    if not path.exists():
        return []

    with path.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        validate_csv_columns(
            fieldnames=reader.fieldnames,
            path=path,
        )

        return list(reader)


def validate_existing_rows(
    rows: list[dict[str, Any]],
    path: Path,
    target_date: date,
) -> None:
    """Validate existing raw rows before merging."""
    seen_ids: set[str] = set()
    expected_date = target_date.isoformat()

    for index, row in enumerate(rows, start=2):
        event_id = str(
            row.get("AW_Event_ID", "")
        ).strip()

        if not event_id:
            raise ValueError(
                f"Existing CSV row {index} has no AW_Event_ID."
            )

        if event_id in seen_ids:
            raise ValueError(
                f"Existing CSV contains duplicate AW_Event_ID "
                f"'{event_id}' around row {index}."
            )

        seen_ids.add(event_id)

        if row.get("Date") != expected_date:
            raise ValueError(
                f"Existing CSV row {index} has Date "
                f"'{row.get('Date')}', expected '{expected_date}'."
            )


def merge_rows(
    existing_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Merge new rows using AW_Event_ID as the natural key."""
    existing_ids = {
        str(row["AW_Event_ID"])
        for row in existing_rows
    }

    added_rows: list[dict[str, Any]] = []
    already_existing_count = 0

    for row in new_rows:
        event_id = str(row["AW_Event_ID"])

        if event_id in existing_ids:
            already_existing_count += 1
            continue

        added_rows.append(row)
        existing_ids.add(event_id)

    merged_rows = [
        *existing_rows,
        *added_rows,
    ]

    merged_rows.sort(
        key=lambda row: (
            row["Start"],
            str(row["AW_Event_ID"]),
        )
    )

    return (
        merged_rows,
        len(added_rows),
        already_existing_count,
    )


def write_csv_atomic(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write the dataset atomically."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8-sig",
            dir=output_path.parent,
            prefix=f".{output_path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            writer = csv.DictWriter(
                temporary_file,
                fieldnames=CSV_COLUMNS,
                extrasaction="raise",
            )

            writer.writeheader()
            writer.writerows(rows)

            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(
            temporary_path,
            output_path,
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


def calculate_duration(
    rows: list[dict[str, Any]],
) -> float:
    """Calculate total duration represented by rows."""
    return sum(
        float(row["Duration_sec"])
        for row in rows
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


def load_one_date(
    client: ActivityWatchClient,
    target_date: date,
    output_directory: Path | None,
    window_bucket: str,
    afk_bucket: str,
    device: str,
) -> dict[str, int | float]:
    """Load and reconcile one calendar date."""
    start, end = get_local_day(target_date)

    print(f"\n--- {target_date.isoformat()} ---")
    print("Retrieving canonical ActivityWatch events...")

    query = build_canonical_query(
        window_bucket_id=window_bucket,
        afk_bucket_id=afk_bucket,
    )

    events = execute_canonical_query(
        client=client,
        query=query,
        start=start,
        end=end,
    )

    retrieved_count = len(events)

    output_path = get_output_path(
        output_directory=output_directory,
        target_date=target_date,
        device=device,
    )

    existing_rows = read_existing_rows(output_path)

    if retrieved_count == 0:
        validate_existing_rows(
            rows=existing_rows,
            path=output_path,
            target_date=target_date,
        )

        if existing_rows:
            total_duration = calculate_duration(existing_rows)

            print(
                "Retrieved from ActivityWatch : 0"
            )
            print(
                f"Existing CSV rows             : "
                f"{len(existing_rows):,}"
            )
            print(
                "Result                        : "
                "ActivityWatch returned no events; "
                "existing Raw_ActivityWatch data "
                "was preserved."
            )
            print(
                f"Total event time              : "
                f"{format_duration(total_duration)}"
            )
            print(
                f"Output                        : "
                f"{output_path}"
            )

            return {
                "retrieved": 0,
                "unique": 0,
                "duplicates": 0,
                "existing": len(existing_rows),
                "already_present": 0,
                "added": 0,
                "final": len(existing_rows),
                "duration": total_duration,
            }

        write_csv_atomic(
            rows=[],
            output_path=output_path,
        )

        print(
            "Retrieved from ActivityWatch : 0"
        )
        print(
            "Existing CSV rows             : 0"
        )
        print(
            "New events added              : 0"
        )
        print(
            "Final CSV rows                : 0"
        )
        print(
            "Total event time              : 0m"
        )
        print(
            "Result                        : "
            "Empty Raw_ActivityWatch dataset "
            "created successfully."
        )
        print(
            f"Output                        : "
            f"{output_path}"
        )

        return {
            "retrieved": 0,
            "unique": 0,
            "duplicates": 0,
            "existing": 0,
            "already_present": 0,
            "added": 0,
            "final": 0,
            "duration": 0.0,
        }

    normalized_rows = normalize_events(
        events=events,
        target_date=target_date,
        device=device,
        bucket_id=window_bucket,
    )

    unique_rows, duplicate_count = deduplicate_rows(
        normalized_rows
    )

    validate_existing_rows(
        rows=existing_rows,
        path=output_path,
        target_date=target_date,
    )

    (
        merged_rows,
        added_count,
        already_existing_count,
    ) = merge_rows(
        existing_rows=existing_rows,
        new_rows=unique_rows,
    )

    write_csv_atomic(
        rows=merged_rows,
        output_path=output_path,
    )

    total_duration = calculate_duration(merged_rows)

    print(
        f"Retrieved from ActivityWatch : "
        f"{retrieved_count:,}"
    )
    print(
        f"Unique ActivityWatch IDs      : "
        f"{len(unique_rows):,}"
    )
    print(
        f"Duplicate retrieved events    : "
        f"{duplicate_count:,}"
    )
    print(
        f"Existing CSV rows             : "
        f"{len(existing_rows):,}"
    )
    print(
        f"Already in CSV                : "
        f"{already_existing_count:,}"
    )
    print(
        f"New events added              : "
        f"{added_count:,}"
    )
    print(
        f"Final CSV rows                : "
        f"{len(merged_rows):,}"
    )
    print(
        f"Total event time              : "
        f"{format_duration(total_duration)}"
    )
    print(
        f"Output                        : "
        f"{output_path}"
    )

    return {
        "retrieved": retrieved_count,
        "unique": len(unique_rows),
        "duplicates": duplicate_count,
        "existing": len(existing_rows),
        "already_present": already_existing_count,
        "added": added_count,
        "final": len(merged_rows),
        "duration": total_duration,
    }


def print_overall_summary(
    target_dates: list[date],
    results: list[dict[str, int | float]],
) -> None:
    """Print the multi-date reconciliation summary."""
    total_retrieved = sum(
        int(result["retrieved"])
        for result in results
    )

    total_unique = sum(
        int(result["unique"])
        for result in results
    )

    total_duplicates = sum(
        int(result["duplicates"])
        for result in results
    )

    total_already_present = sum(
        int(result["already_present"])
        for result in results
    )

    total_added = sum(
        int(result["added"])
        for result in results
    )

    total_duration = sum(
        float(result["duration"])
        for result in results
    )

    print()
    print("=" * 60)
    print("=== Overall Raw_ActivityWatch Summary ===")
    print(
        f"Dates processed              : "
        f"{len(target_dates):,}"
    )
    print(
        f"ActivityWatch events         : "
        f"{total_retrieved:,}"
    )
    print(
        f"Unique ActivityWatch IDs     : "
        f"{total_unique:,}"
    )
    print(
        f"Duplicate retrieved events   : "
        f"{total_duplicates:,}"
    )
    print(
        f"Already present in CSV       : "
        f"{total_already_present:,}"
    )
    print(
        f"New events added             : "
        f"{total_added:,}"
    )
    print(
        f"Total event duration         : "
        f"{format_duration(total_duration)}"
    )
    print("=" * 60)

    if total_added > 0:
        print(
            "RESULT: Raw_ActivityWatch datasets "
            "were updated successfully."
        )
    elif total_retrieved > 0:
        print(
            "RESULT: Raw_ActivityWatch datasets "
            "were already up to date."
        )
    else:
        print(
            "RESULT: No ActivityWatch events "
            "were found for the requested dates."
        )


def main() -> int:
    """Run the ActivityWatch raw loader."""
    args = parse_arguments()

    try:
        target_dates = resolve_target_dates(args)

        first_start, _ = get_local_day(target_dates[0])
        _, last_end = get_local_day(target_dates[-1])

        print("# ActivityWatch Raw Loader")
        print()

        print(
            f"Server : http://{args.host}:{args.port}"
        )

        if len(target_dates) == 1:
            print(
                f"Date   : "
                f"{target_dates[0].isoformat()}"
            )
        else:
            print(
                f"Dates  : "
                f"{target_dates[0].isoformat()} → "
                f"{target_dates[-1].isoformat()}"
            )

        print(
            f"Range  : "
            f"{first_start.isoformat()} → "
            f"{last_end.isoformat()}"
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

        client = create_client(
            host=args.host,
            port=args.port,
        )

        server_info = client.get_info()

        device = str(
            server_info.get(
                "hostname",
                "Unknown Device",
            )
        )

        print("=== ActivityWatch Server ===")
        print(f"Hostname : {device}")
        print(
            f"Testing  : "
            f"{server_info.get('testing', 'unknown')}"
        )
        print()

        window_bucket, afk_bucket = get_bucket_ids(client)

        print("=== Selected Buckets ===")
        print(f"Window : {window_bucket}")
        print(f"AFK    : {afk_bucket}")
        print(f"Dates  : {len(target_dates):,}")

        if args.output_dir is None:
            preview_path = get_activitywatch_raw_path(
                device=device,
                target_date=target_dates[0],
            )
            print(
                f"Output : {preview_path.parent}"
            )
            print(
                "Path   : canonical device-specific "
                "ActivityWatch Raw dataset"
            )
        else:
            print(
                f"Output : {args.output_dir}"
            )
            print(
                "Path   : custom/legacy override"
            )

        results: list[dict[str, int | float]] = []

        for target_date in target_dates:
            result = load_one_date(
                client=client,
                target_date=target_date,
                output_directory=args.output_dir,
                window_bucket=window_bucket,
                afk_bucket=afk_bucket,
                device=device,
            )

            results.append(result)

        print_overall_summary(
            target_dates=target_dates,
            results=results,
        )

        return 0

    except KeyboardInterrupt:
        print()
        print("Cancelled.")
        return 130

    except Exception as exc:
        print(
            f"\nERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())