# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\activitywatch\activitywatch_exporter.py

"""Export ActivityWatch canonical events to the Raw_ActivityWatch dataset.

This module reads ActivityWatch data without modifying the ActivityWatch
server. It exports one local calendar day to a deterministic CSV file.

The exported dataset is intended to become the raw ActivityWatch layer
of the System Tracker and should therefore preserve event-level detail.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from aw_client import ActivityWatchClient
from aw_client.queries import DesktopQueryParams, canonicalEvents


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5600

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIRECTORY = SCRIPT_DIRECTORY / "output"

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
    "Window_Title",
    "AW_Category",
    "AW_Subcategory",
]


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Export ActivityWatch canonical events to "
            "Raw_ActivityWatch CSV."
        )
    )

    parser.add_argument(
        "--date",
        dest="target_date",
        help=(
            "Calendar date to export in YYYY-MM-DD format. "
            "Defaults to today."
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
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=(
            "Directory for exported CSV files. "
            f"Default: {DEFAULT_OUTPUT_DIRECTORY}"
        ),
    )

    return parser.parse_args()


def parse_target_date(value: str | None) -> date:
    """Parse the requested date or use today's local date."""
    if value is None:
        return datetime.now().astimezone().date()

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def get_local_day(
    target_date: date,
) -> tuple[datetime, datetime]:
    """Return the timezone-aware start and end of a local calendar day."""
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
    """Find the ActivityWatch window and AFK bucket IDs."""
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
    """Execute the canonical query and unwrap its response."""
    result = client.query(
        query=query,
        timeperiods=[(start, end)],
        name="system-tracker-export",
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
            "Unexpected ActivityWatch query response format: "
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
    """Return an event's duration in seconds."""
    duration = event.get("duration", 0)

    if isinstance(duration, timedelta):
        return duration.total_seconds()

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
    """Return the event's data dictionary."""
    data = event.get("data", {})

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
    return timestamp.astimezone().isoformat(
        timespec="milliseconds"
    )


def normalize_event(
    event: dict[str, Any],
    target_date: date,
    device: str,
    bucket_id: str,
) -> dict[str, Any]:
    """Convert a canonical ActivityWatch event into a CSV row."""
    timestamp_utc = parse_event_timestamp(event)
    timestamp_local = timestamp_utc.astimezone()

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

    return {
        "Date": target_date.isoformat(),
        "Start": format_timestamp(timestamp_local),
        "End": format_timestamp(end_local),
        "Duration_sec": round(duration_seconds, 3),
        "Device": device,
        "Source": "ActivityWatch",
        "Bucket": bucket_id,
        "AW_Event_ID": event.get("id", ""),
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


def write_csv(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write normalized rows to a UTF-8 CSV file."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
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
        round(max(seconds, 0.0) / 60)
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
    """Calculate total duration by full ActivityWatch category path."""
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
            totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )


def print_summary(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Print the export summary."""
    total_duration = calculate_duration(rows)
    category_totals = calculate_category_totals(rows)

    print()
    print("=== Export Summary ===")
    print(f"Events exported : {len(rows):,}")
    print(
        f"Total duration  : "
        f"{format_duration(total_duration)}"
    )
    print(f"Output file     : {output_path}")

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

    print()
    print(
        "RESULT: Raw_ActivityWatch CSV "
        "created successfully."
    )


def main() -> int:
    """Run the ActivityWatch exporter."""
    args = parse_arguments()

    try:
        target_date = parse_target_date(
            args.target_date
        )

        start, end = get_local_day(
            target_date
        )

        print("# ActivityWatch Exporter")
        print()
        print(
            f"Server : "
            f"http://{args.host}:{args.port}"
        )
        print(
            f"Date   : "
            f"{target_date.isoformat()}"
        )
        print(
            f"Range  : "
            f"{start.isoformat()} → {end.isoformat()}"
        )
        print("Mode   : READ ONLY")
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

        window_bucket, afk_bucket = get_bucket_ids(
            client
        )

        print("=== Selected Buckets ===")
        print(f"Window : {window_bucket}")
        print(f"AFK    : {afk_bucket}")
        print()

        print(
            "Retrieving canonical ActivityWatch events..."
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
            f"Canonical events retrieved: "
            f"{len(events):,}"
        )

        rows = normalize_events(
            events=events,
            target_date=target_date,
            device=device,
            bucket_id=window_bucket,
        )

        output_path = (
            args.output_dir
            / (
                "Raw_ActivityWatch_"
                f"{target_date.isoformat()}.csv"
            )
        )

        write_csv(
            rows=rows,
            output_path=output_path,
        )

        print_summary(
            rows=rows,
            output_path=output_path,
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