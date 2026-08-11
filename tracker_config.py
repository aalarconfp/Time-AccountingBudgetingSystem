# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\tracker_config.py

"""Shared configuration for the Personal Life Tracker system."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from config.paths import PROJECT_ROOT


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_DIRECTORY = PROJECT_ROOT

# Legacy dataset locations remain active during the migration so the
# validated ActivityWatch data does not need to move yet.
OUTPUT_DIRECTORY = PROJECT_DIRECTORY / "output"
RAW_ACTIVITYWATCH_DIRECTORY = OUTPUT_DIRECTORY
FACT_TIME_DIRECTORY = OUTPUT_DIRECTORY / "Fact_Time"
DAILY_TIME_DIRECTORY = OUTPUT_DIRECTORY / "Daily_Time"
ANALYSIS_DIRECTORY = OUTPUT_DIRECTORY / "Analysis"


# ---------------------------------------------------------------------------
# Dataset filenames
# ---------------------------------------------------------------------------

RAW_ACTIVITYWATCH_FILE_PREFIX = "Raw_ActivityWatch_"
FACT_TIME_FILE_PREFIX = "Fact_Time_"

CSV_SUFFIX = ".csv"


def raw_activitywatch_path(target_date: date) -> Path:
    """Return the Raw ActivityWatch CSV path for a date."""
    return (
        OUTPUT_DIRECTORY
        / (
            f"{RAW_ACTIVITYWATCH_FILE_PREFIX}"
            f"{target_date.isoformat()}"
            f"{CSV_SUFFIX}"
        )
    )


def fact_time_path(target_date: date) -> Path:
    """Return the Fact_Time CSV path for a date."""
    return (
        FACT_TIME_DIRECTORY
        / (
            f"{FACT_TIME_FILE_PREFIX}"
            f"{target_date.isoformat()}"
            f"{CSV_SUFFIX}"
        )
    )


# ---------------------------------------------------------------------------
# ActivityWatch configuration
# ---------------------------------------------------------------------------

ACTIVITYWATCH_HOST = "localhost"
ACTIVITYWATCH_PORT = 5600
ACTIVITYWATCH_PROTOCOL = "http"

ACTIVITYWATCH_SERVER = (
    f"{ACTIVITYWATCH_PROTOCOL}://"
    f"{ACTIVITYWATCH_HOST}:"
    f"{ACTIVITYWATCH_PORT}"
)


# ---------------------------------------------------------------------------
# Local timezone
# ---------------------------------------------------------------------------

LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo

if LOCAL_TIMEZONE is None:
    raise RuntimeError(
        "Unable to determine the local timezone."
    )


# ---------------------------------------------------------------------------
# Completed-day policy
# ---------------------------------------------------------------------------

EXCLUDE_CURRENT_DAY_BY_DEFAULT = True


def today_local() -> date:
    """Return today's local calendar date."""
    return datetime.now(
        LOCAL_TIMEZONE
    ).date()


def latest_completed_date() -> date:
    """Return the latest fully completed calendar day."""
    return today_local() - timedelta(days=1)


def is_completed_date(
    target_date: date,
    include_today: bool = False,
) -> bool:
    """Return whether a date is eligible for normal processing."""
    if include_today:
        return target_date <= today_local()

    return target_date <= latest_completed_date()


def validate_completed_date(
    target_date: date,
    include_today: bool = False,
) -> None:
    """Raise an error when a date violates the completed-day rule."""
    if is_completed_date(
        target_date=target_date,
        include_today=include_today,
    ):
        return

    raise ValueError(
        f"{target_date.isoformat()} is the current day or a future date "
        "and is excluded by default. "
        "Use --include-today to explicitly include today's data."
    )


# ---------------------------------------------------------------------------
# Dataset schemas
# ---------------------------------------------------------------------------

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
    "Category",
}

FACT_TIME_OPTIONAL_COLUMNS = {
    "Window_Title",
    "Subcategory",
}

RAW_ACTIVITYWATCH_REQUIRED_COLUMNS = {
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
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

TIMESTAMP_TOLERANCE_SECONDS = 0.01


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def ensure_output_directories() -> None:
    """Create required output directories if they do not exist."""
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    FACT_TIME_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )