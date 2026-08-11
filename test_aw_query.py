# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\test_aw_query.py

from datetime import datetime, timedelta

from aw_client import ActivityWatchClient


def main() -> None:
    """Test ActivityWatch query execution."""
    client = ActivityWatchClient(
        client_name="diagnostic",
        host="localhost",
        port=5600,
    )

    buckets = client.get_buckets()

    window_bucket = next(
        bucket_id
        for bucket_id, bucket in buckets.items()
        if bucket.get("type") == "currentwindow"
    )

    start = datetime.now().astimezone().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    end = start + timedelta(days=1)

    query = "\n".join(
        [
            f'events = query_bucket("{window_bucket}");',
            "RETURN = events;",
        ]
    )

    print(f"Testing bucket: {window_bucket}")
    print("Query:")
    print(query)
    print()

    events = client.query(
        query=query,
        timeperiods=[(start, end)],
    )

    print(f"SUCCESS: {len(events):,} events")
    print()
    print("First 2 events:")

    for event in events[:2]:
        print(event)


if __name__ == "__main__":
    main()