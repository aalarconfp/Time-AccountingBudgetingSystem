# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\activitywatch_collector.py

"""Read-only ActivityWatch collector for Phase 1 validation.

Connects to the local ActivityWatch server, retrieves raw and canonical
activity for a local calendar day, and reports activity totals and
category breakdowns.

This version does not modify ActivityWatch data or external files.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from aw_client import ActivityWatchClient
from aw_client.queries import DesktopQueryParams, canonicalEvents


SERVER_HOST = "localhost"
SERVER_PORT = 5600
CLIENT_NAME = "system-tracker"

WINDOW_BUCKET_TYPE = "currentwindow"
AFK_BUCKET_TYPE = "afkstatus"


@dataclass(frozen=True)
class BucketSelection:
    """ActivityWatch buckets required by the collector."""

    window: str
    afk: str


def create_client() -> ActivityWatchClient:
    """Create an ActivityWatch client."""
    return ActivityWatchClient(
        client_name=CLIENT_NAME,
        host=SERVER_HOST,
        port=SERVER_PORT,
        testing=False,
    )


def get_bucket_selection(
    client: ActivityWatchClient,
) -> BucketSelection:
    """Find the window and AFK buckets."""
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
            f"Using: {window_buckets[0]}"
        )

    if len(afk_buckets) > 1:
        print(
            "WARNING: Multiple AFK buckets found. "
            f"Using: {afk_buckets[0]}"
        )

    return BucketSelection(
        window=window_buckets[0],
        afk=afk_buckets[0],
    )


def get_local_day() -> tuple[datetime, datetime]:
    """Return today's local timezone-aware calendar range."""
    now = datetime.now().astimezone()

    start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    end = start + timedelta(days=1)

    return start, end


def get_event_duration(event: Any) -> float:
    """Return event duration in seconds."""
    duration = (
        event.duration
        if hasattr(event, "duration")
        else event.get("duration", 0)
    )

    if isinstance(duration, timedelta):
        return duration.total_seconds()

    return float(duration)


def calculate_duration(events: list[Any]) -> float:
    """Calculate total duration for a collection of events."""
    return sum(
        get_event_duration(event)
        for event in events
    )


def get_event_data(event: Any) -> dict[str, Any]:
    """Return event data regardless of event representation."""
    if hasattr(event, "data"):
        data = event.data
    else:
        data = event.get("data", {})

    if isinstance(data, dict):
        return data

    return {}


def get_category(event: Any) -> str:
    """Return the ActivityWatch category path."""
    data = get_event_data(event)

    category = data.get("$category")

    if category is None:
        category = data.get("category")

    if category is None:
        category = data.get("app")

    if category is None:
        return "Uncategorized"

    if isinstance(category, list):
        return " > ".join(str(value) for value in category)

    return str(category)


def build_category_totals(
    events: list[Any],
) -> dict[str, float]:
    """Aggregate canonical duration by ActivityWatch category."""
    totals: defaultdict[str, float] = defaultdict(float)

    for event in events:
        duration = get_event_duration(event)

        if duration <= 0:
            continue

        totals[get_category(event)] += duration

    return dict(
        sorted(
            totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )


def format_duration(seconds: float) -> str:
    """Format seconds as hours and minutes."""
    total_minutes = int(round(max(seconds, 0.0) / 60))

    hours, minutes = divmod(total_minutes, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m"


def format_percentage(
    value: float,
    total: float,
) -> str:
    """Format a value as a percentage of a total."""
    if total <= 0:
        return "0.0%"

    return f"{value / total * 100:.1f}%"


def print_header(
    start: datetime,
    end: datetime,
) -> None:
    """Print collector diagnostic header."""
    print("ActivityWatch Collector — Phase 1")
    print("=" * 55)
    print(f"Server : http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"Date   : {start.date()}")
    print(
        f"Range  : "
        f"{start.isoformat()} → {end.isoformat()}"
    )
    print("Mode   : READ ONLY")
    print()


def print_server_info(
    client: ActivityWatchClient,
) -> None:
    """Print ActivityWatch server information."""
    info = client.get_info()

    print("=== ActivityWatch Server ===")
    print(f"Hostname : {info.get('hostname', 'unknown')}")
    print(f"Testing  : {info.get('testing', 'unknown')}")
    print()


def print_bucket_summary(
    buckets: BucketSelection,
) -> None:
    """Print selected ActivityWatch buckets."""
    print("=== Selected Buckets ===")
    print(f"Window : {buckets.window}")
    print(f"AFK    : {buckets.afk}")
    print()


def get_raw_window_events(
    client: ActivityWatchClient,
    bucket_id: str,
    start: datetime,
    end: datetime,
) -> list[Any]:
    """Retrieve raw window events for the selected period."""
    return client.get_events(
        bucket_id=bucket_id,
        start=start,
        end=end,
        limit=-1,
    )


def build_canonical_query(
    buckets: BucketSelection,
) -> str:
    """Build ActivityWatch's canonical desktop query."""
    params = DesktopQueryParams(
        bid_window=buckets.window,
        bid_afk=buckets.afk,
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
) -> list[Any]:
    """Execute the canonical query and unwrap its response."""
    result = client.query(
        query=query,
        timeperiods=[(start, end)],
        name="system-tracker-canonical",
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
            f"expected a list of events, received "
            f"{type(events).__name__}."
        )

    return events


def print_activity_summary(
    raw_events: list[Any],
    canonical_events: list[Any],
) -> None:
    """Print raw and canonical activity totals."""
    raw_duration = calculate_duration(raw_events)
    canonical_duration = calculate_duration(canonical_events)

    difference = raw_duration - canonical_duration

    print("=== Activity Summary ===")
    print(
        f"Raw window events : "
        f"{len(raw_events):,}"
    )
    print(
        f"Raw window time   : "
        f"{format_duration(raw_duration)}"
    )
    print(
        f"Canonical events  : "
        f"{len(canonical_events):,}"
    )
    print(
        f"Canonical time    : "
        f"{format_duration(canonical_duration)}"
    )
    print(
        f"AFK-filtered time : "
        f"{format_duration(canonical_duration)}"
    )
    print(
        f"Removed by AFK    : "
        f"{format_duration(max(difference, 0.0))}"
    )

    if raw_duration > 0:
        print(
            f"Canonical/raw     : "
            f"{canonical_duration / raw_duration * 100:.1f}%"
        )

    print()


def print_category_summary(
    canonical_events: list[Any],
) -> None:
    """Print canonical duration by ActivityWatch category."""
    totals = build_category_totals(canonical_events)

    print("=== Category Breakdown ===")

    if not totals:
        print("No categorized activity found.")
        print()
        return

    total_duration = sum(totals.values())

    for category, seconds in totals.items():
        print(
            f"{format_duration(seconds):>9} "
            f"{format_percentage(seconds, total_duration):>7}  "
            f"{category}"
        )

    print()


def print_event_samples(
    canonical_events: list[Any],
    limit: int = 10,
) -> None:
    """Print the raw structure of canonical events."""
    print("=== Canonical Event Samples ===")

    if not canonical_events:
        print("No canonical events.")
        print()
        return

    for index, event in enumerate(canonical_events[:limit], start=1):
        print(f"\nEvent #{index}")
        print(f"Type: {type(event).__name__}")
        print(f"Raw: {event}")

        if isinstance(event, dict):
            print(f"Keys: {list(event.keys())}")

            timestamp = (
                event.get("timestamp")
                or event.get("start")
            )

            print(f"Timestamp: {timestamp}")
            print(f"Duration: {event.get('duration')}")
            print(f"Data: {event.get('data')}")

        elif hasattr(event, "__dict__"):
            print(f"Attributes: {event.__dict__}")

    print()
    
def print_diagnostic_result(
    raw_events: list[Any],
    canonical_events: list[Any],
) -> None:
    """Print final Phase 1 diagnostic status."""
    print("=== Diagnostic Result ===")

    if raw_events:
        print(
            "PASS  Raw ActivityWatch window events "
            "were retrieved."
        )
    else:
        print(
            "WARN  No raw window events were found "
            "for this date."
        )

    if canonical_events:
        print(
            "PASS  ActivityWatch canonical events "
            "were successfully retrieved."
        )
    else:
        print(
            "WARN  No canonical events were returned "
            "for this date."
        )

    if raw_events and canonical_events:
        print()
        print(
            "RESULT: ActivityWatch → Python collector "
            "pipeline is working."
        )
        print(
            "Next step: validate category mappings and "
            "build the Raw_ActivityWatch dataset."
        )
    else:
        print()
        print(
            "RESULT: The connection works, but the selected "
            "date returned insufficient activity data."
        )


def main() -> None:
    """Run the read-only ActivityWatch collector."""
    start, end = get_local_day()

    print_header(
        start=start,
        end=end,
    )

    try:
        client = create_client()

        print_server_info(client)

        buckets = get_bucket_selection(client)

        print_bucket_summary(buckets)

        raw_events = get_raw_window_events(
            client=client,
            bucket_id=buckets.window,
            start=start,
            end=end,
        )

        print(
            f"Raw window events retrieved: "
            f"{len(raw_events):,}"
        )
        print()

        print(
            "Calculating canonical ActivityWatch events..."
        )

        query = build_canonical_query(buckets)

        canonical_events = execute_canonical_query(
            client=client,
            query=query,
            start=start,
            end=end,
        )

        print(
            "Canonical query executed successfully."
        )
        print()

        print_activity_summary(
            raw_events=raw_events,
            canonical_events=canonical_events,
        )

        print_category_summary(
            canonical_events=canonical_events,
        )

        print_event_samples(
            canonical_events=canonical_events,
            limit=10,
        )

        print_diagnostic_result(
            raw_events=raw_events,
            canonical_events=canonical_events,
        )

    except KeyboardInterrupt:
        print()
        print("Cancelled.")

    except Exception as exc:
        print()
        print("ERROR:")
        print(f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()