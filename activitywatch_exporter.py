# G:\My Drive\Personal Life\Habit and Wellness\System_Tracker\activitywatch_exporter.py

"""Export ActivityWatch canonical events to the canonical Raw layer.

The exporter reads ActivityWatch data without modifying the ActivityWatch
server. It exports one local calendar day to a deterministic source/device
specific CSV file.

ActivityWatch's canonical desktop query stores the classification hierarchy
in the event data under the "$category" field. That source field is preserved
as Category/Subcategory in the Raw dataset.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aw_client import ActivityWatchClient
from aw_client.queries import DesktopQueryParams, canonicalEvents

from config.paths import get_source_raw_root
from config.sources import (
    SourceDefinition,
    SourceType,
    get_source_definition,
)
from config.tracker_config import DEFAULT_TIMEZONE


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5600
CLIENT_NAME = "system-tracker-exporter"

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
    "Title",
    "URL",
    "AW_Category",
    "AW_Subcategory",
    "AW_Category_Path",
]


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Export ActivityWatch canonical events to a "
            "source-specific Raw ActivityWatch CSV."
        )
    )

    parser.add_argument(
        "--date",
        dest="target_date",
        help=(
            "Calendar date to export in YYYY-MM-DD format. "
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
            "Configured ActivityWatch source. "
            "Default: asus_laptop."
        ),
    )

    parser.add_argument(
        "--host",
        default=None,
        help=(
            f"ActivityWatch server host. "
            f"Default: {DEFAULT_HOST}"
        ),
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            f"ActivityWatch server port. "
            f"Default: {DEFAULT_PORT}"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Project output directory. "
            "Defaults to the configured project output directory."
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


def parse_target_date(value: str | None) -> date:
    """Parse the requested date or use today's project-local date."""
    if value is None:
        return datetime.now(
            get_project_timezone()
        ).date()

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


def validate_completed_date(target_date: date) -> None:
    """Reject dates that have not yet completed."""
    latest_date = latest_completed_date()

    if target_date > latest_date:
        raise ValueError(
            f"Date {target_date.isoformat()} is not a "
            f"completed day. Latest completed date is "
            f"{latest_date.isoformat()}."
        )


def get_local_day(
    target_date: date,
) -> tuple[datetime, datetime]:
    """Return timezone-aware boundaries for a project-local day."""
    timezone = get_project_timezone()

    start = datetime.combine(
        target_date,
        datetime.min.time(),
        tzinfo=timezone,
    )

    end = start + timedelta(days=1)

    return start, end


def create_client(
    host: str,
    port: int,
) -> ActivityWatchClient:
    """Create an ActivityWatch API client."""
    return ActivityWatchClient(
        CLIENT_NAME,
        host=host,
        port=port,
    )


def bucket_matches_device(
    bucket_id: str,
    bucket: dict[str, Any],
    device: str,
) -> bool:
    """Return whether an ActivityWatch bucket belongs to a device."""
    hostname = str(
        bucket.get("hostname", "")
    ).strip()

    return (
        hostname == device
        or bucket_id.endswith(f"_{device}")
        or bucket_id == device
    )


def get_bucket_ids(
    client: ActivityWatchClient,
    device: str,
) -> tuple[str, str]:
    """Find the ActivityWatch window and AFK buckets for a device."""
    buckets = client.get_buckets()

    window_buckets = [
        bucket_id
        for bucket_id, bucket in buckets.items()
        if (
            bucket.get("type") == WINDOW_BUCKET_TYPE
            and bucket_matches_device(
                bucket_id=bucket_id,
                bucket=bucket,
                device=device,
            )
        )
    ]

    afk_buckets = [
        bucket_id
        for bucket_id, bucket in buckets.items()
        if (
            bucket.get("type") == AFK_BUCKET_TYPE
            and bucket_matches_device(
                bucket_id=bucket_id,
                bucket=bucket,
                device=device,
            )
        )
    ]

    if not window_buckets:
        raise RuntimeError(
            "No currentwindow ActivityWatch bucket was found "
            f"for device '{device}'."
        )

    if not afk_buckets:
        raise RuntimeError(
            "No afkstatus ActivityWatch bucket was found "
            f"for device '{device}'."
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

    if not query.rstrip().endswith(
        "RETURN = events;"
    ):
        query += "\nRETURN = events;"

    return query


def execute_canonical_query(
    client: ActivityWatchClient,
    query: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Execute the canonical ActivityWatch query."""
    result = client.query(
        query=query,
        timeperiods=[(start, end)],
        name="system-tracker-export",
        cache=False,
    )

    if len(result) != 1:
        raise RuntimeError(
            "Unexpected ActivityWatch query response: "
            f"expected one result, received {len(result)}."
        )

    events = result[0]

    if not isinstance(events, list):
        raise RuntimeError(
            "Unexpected ActivityWatch query response format: "
            f"expected a list, received {type(events).__name__}."
        )

    return events


def parse_event_timestamp(
    event: dict[str, Any],
) -> datetime:
    """Parse an ActivityWatch event timestamp."""
    timestamp = event.get("timestamp")

    if timestamp is None:
        raise ValueError(
            f"ActivityWatch event {event.get('id')} "
            "has no timestamp."
        )

    if isinstance(timestamp, datetime):
        parsed = timestamp
    else:
        parsed = datetime.fromisoformat(
            str(timestamp).replace(
                "Z",
                "+00:00",
            )
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
    """Return an event's duration in seconds."""
    duration = event.get(
        "duration",
        0,
    )

    if isinstance(duration, timedelta):
        seconds = duration.total_seconds()
    else:
        try:
            seconds = float(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"ActivityWatch event {event.get('id')} "
                f"has invalid duration: {duration!r}."
            ) from exc

    if seconds < 0:
        raise ValueError(
            f"ActivityWatch event {event.get('id')} "
            f"has negative duration: {seconds}."
        )

    return seconds


def get_event_data(
    event: dict[str, Any],
) -> dict[str, Any]:
    """Return the ActivityWatch event data dictionary."""
    data = event.get("data")

    if not isinstance(data, dict):
        return {}

    return data


def get_category_path(
    data: dict[str, Any],
) -> list[str]:
    """Return the ActivityWatch category hierarchy."""
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
    """Format a timestamp for CSV storage."""
    return timestamp.astimezone(
        get_project_timezone()
    ).isoformat(
        timespec="milliseconds"
    )


def normalize_event(
    event: dict[str, Any],
    target_date: date,
    device: str,
    bucket_id: str,
) -> dict[str, Any]:
    """Convert a canonical ActivityWatch event into a CSV row."""
    timestamp = parse_event_timestamp(event)
    timestamp_local = timestamp.astimezone(
        get_project_timezone()
    )

    duration_seconds = get_event_duration(event)

    end_local = timestamp_local + timedelta(
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

    category_path_string = (
        " > ".join(category_path)
        if category_path
        else "Uncategorized"
    )

    app = str(
        data.get("app", "")
        or ""
    )

    title = str(
        data.get("title", "")
        or ""
    )

    url = str(
        data.get("url", "")
        or ""
    )

    return {
        "Date": target_date.isoformat(),
        "Start": format_timestamp(
            timestamp_local
        ),
        "End": format_timestamp(
            end_local
        ),
        "Duration_sec": round(
            duration_seconds,
            3,
        ),
        "Device": device,
        "Source": "ActivityWatch",
        "Bucket": bucket_id,
        "AW_Event_ID": str(
            event.get("id", "")
            or ""
        ),
        "App": app,
        "Title": title,
        "URL": url,
        "AW_Category": category,
        "AW_Subcategory": subcategory,
        "AW_Category_Path": category_path_string,
    }


def normalize_events(
    events: list[dict[str, Any]],
    target_date: date,
    device: str,
    bucket_id: str,
) -> list[dict[str, Any]]:
    """Normalize and chronologically sort canonical events."""
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
            str(row["AW_Event_ID"]),
        )
    )

    return rows


def deduplicate_events(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Remove duplicate events by ActivityWatch event ID."""
    unique_rows: dict[str, dict[str, Any]] = {}
    duplicates = 0

    for row in rows:
        event_id = str(
            row["AW_Event_ID"]
        )

        if event_id in unique_rows:
            duplicates += 1
            continue

        unique_rows[event_id] = row

    deduplicated = list(
        unique_rows.values()
    )

    deduplicated.sort(
        key=lambda row: (
            row["Start"],
            str(row["AW_Event_ID"]),
        )
    )

    return deduplicated, duplicates


def write_csv(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write normalized rows to a UTF-8 CSV file."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = output_path.with_suffix(
        ".tmp"
    )

    with temporary_path.open(
        mode="w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_COLUMNS,
            extrasaction="raise",
    )

        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(
        output_path
    )


def calculate_duration(
    rows: list[dict[str, Any]],
) -> float:
    """Calculate total exported event duration."""
    return sum(
        float(row["Duration_sec"])
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


def calculate_category_totals(
    rows: list[dict[str, Any]],
) -> dict[str, float]:
    """Calculate total duration by ActivityWatch category path."""
    totals: dict[str, float] = {}

    for row in rows:
        category = row["AW_Category"]

        if row["AW_Subcategory"]:
            category = (
                f"{category} > "
                f"{row['AW_Subcategory']}"
            )

        totals[category] = (
            totals.get(category, 0.0)
            + float(row["Duration_sec"])
        )

    return dict(
        sorted(
            totals.items()
        )
    )


def print_export_summary(
    rows: list[dict[str, Any]],
    duplicate_count: int,
    output_path: Path,
) -> None:
    """Print the export summary."""
    total_duration = calculate_duration(
        rows
    )

    category_totals = calculate_category_totals(
        rows
    )

    print()
    print("=== Export Summary ===")
    print(
        f"Rows exported       : {len(rows):,}"
    )
    print(
        f"Unique event IDs     : "
        f"{len({row['AW_Event_ID'] for row in rows}):,}"
    )
    print(
        f"Duplicate events removed: "
        f"{duplicate_count:,}"
    )
    print(
        f"Total event time     : "
        f"{format_duration(total_duration)}"
    )
    print(
        f"Output              : "
        f"{output_path}"
    )

    print()
    print("=== Category Breakdown ===")

    if not category_totals:
        print("No categorized events.")
        return

    for category, seconds in category_totals.items():
        percentage = (
            seconds / total_duration * 100
            if total_duration > 0
            else 0.0
        )

        print(
            f"{format_duration(seconds):>9} "
            f"{percentage:>6.1f}%  "
            f"{category}"
        )


def get_output_path(
    source: SourceDefinition,
    target_date: date,
    output_directory_override: Path | None,
) -> Path:
    """Return the canonical Raw output path."""
    default_root = get_source_raw_root(
        SourceType.ACTIVITYWATCH
    )

    source_root = (
        default_root
        / (
            source.device
            if source.device
            else source.source.value
        )
    )

    filename = (
        f"Raw_ActivityWatch_"
        f"{target_date.isoformat()}.csv"
    )

    if output_directory_override is None:
        return source_root / filename

    return (
        output_directory_override
        / "Raw"
        / "ActivityWatch"
        / (
            source.device
            if source.device
            else source.source.value
        )
        / filename
    )


def main() -> int:
    """Run the ActivityWatch exporter."""
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

        if source.device is None:
            raise ValueError(
                f"ActivityWatch source '{args.source}' "
                "has no device."
            )

        host = (
            args.host
            if args.host is not None
            else DEFAULT_HOST
        )

        port = (
            args.port
            if args.port is not None
            else DEFAULT_PORT
        )

        target_date = parse_target_date(
            args.target_date
        )

        validate_completed_date(
            target_date
        )

        start, end = get_local_day(
            target_date
        )

        output_path = get_output_path(
            source=source,
            target_date=target_date,
            output_directory_override=args.output_dir,
        )

        print("# ActivityWatch Exporter")
        print()
        print(
            f"Source   : {args.source}"
        )
        print(
            f"Context  : {source.context}"
        )
        print(
            f"Device   : {source.device}"
        )
        print(
            f"Timezone : {DEFAULT_TIMEZONE}"
        )
        print(
            f"Server   : "
            f"http://{host}:{port}"
        )
        print(
            f"Date     : "
            f"{target_date.isoformat()}"
        )
        print(
            f"Range    : "
            f"{start.isoformat()} → "
            f"{end.isoformat()}"
        )
        print("Mode     : READ ONLY")
        print()

        client = create_client(
            host=host,
            port=port,
        )

        server_info = client.get_info()

        actual_device = str(
            server_info.get(
                "hostname",
                "Unknown Device",
            )
        )

        testing = server_info.get(
            "testing",
            "unknown",
        )

        print("=== ActivityWatch Server ===")
        print(
            f"Hostname : {actual_device}"
        )
        print(
            f"Testing  : {testing}"
        )

        if actual_device != source.device:
            print(
                "WARNING  : Configured device "
                f"'{source.device}' does not match "
                f"server hostname '{actual_device}'."
            )

        window_bucket, afk_bucket = get_bucket_ids(
            client=client,
            device=source.device,
        )

        print()
        print("=== Selected Buckets ===")
        print(
            f"Window   : {window_bucket}"
        )
        print(
            f"AFK      : {afk_bucket}"
        )

        print()
        print(
            "Retrieving canonical "
            "ActivityWatch events..."
        )

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

        print(
            f"Retrieved from ActivityWatch : "
            f"{len(events):,}"
        )

        rows = normalize_events(
            events=events,
            target_date=target_date,
            device=source.device,
            bucket_id=window_bucket,
        )

        rows, duplicate_count = (
            deduplicate_events(rows)
        )

        print(
            f"Unique exported events       : "
            f"{len(rows):,}"
        )

        write_csv(
            rows=rows,
            output_path=output_path,
        )

        print_export_summary(
            rows=rows,
            duplicate_count=duplicate_count,
            output_path=output_path,
        )

        print()
        print(
            "RESULT: ActivityWatch export "
            "completed successfully."
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