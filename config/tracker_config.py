"""Central project configuration.

This module defines stable project-level paths and defaults. Source-specific
definitions live in ``config.sources`` and taxonomy definitions live in
``config.taxonomy``.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from config.sources import ASUS_LAPTOP, DESKTOP, HABIT, IPHONE, SourceDefinition


PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INPUT_DIRECTORY = PROJECT_ROOT / "input"
DOCUMENTATION_DIRECTORY = PROJECT_ROOT / "docs"
TEST_DIRECTORY = PROJECT_ROOT / "tests"

LEGACY_RAW_ACTIVITYWATCH_DIRECTORY = (
    OUTPUT_DIRECTORY / "Raw" / "_ActivityWatch"
)
LEGACY_FACT_TIME_DIRECTORY = OUTPUT_DIRECTORY / "Fact_Time"
LEGACY_DAILY_TIME_DIRECTORY = OUTPUT_DIRECTORY / "Daily_Time"

RAW_DIRECTORY = OUTPUT_DIRECTORY / "Raw"
FACT_DIRECTORY = OUTPUT_DIRECTORY / "Fact"
DAILY_DIRECTORY = OUTPUT_DIRECTORY / "Daily"
INTEGRATED_DIRECTORY = OUTPUT_DIRECTORY / "Integrated"
ANALYSIS_DIRECTORY = OUTPUT_DIRECTORY / "Analysis"

ACTIVITYWATCH_SERVER_URL = "http://localhost:5600"

DEFAULT_TIMEZONE = "America/Bogota"

SOURCE_CONFIGURATIONS: tuple[SourceDefinition, ...] = (
    ASUS_LAPTOP,
    DESKTOP,
    IPHONE,
    HABIT,
)


def ensure_project_directories() -> None:
    """Create directories required by the new architecture."""
    for directory in (
        INPUT_DIRECTORY,
        DOCUMENTATION_DIRECTORY,
        TEST_DIRECTORY,
        RAW_DIRECTORY,
        FACT_DIRECTORY,
        DAILY_DIRECTORY,
        INTEGRATED_DIRECTORY,
        ANALYSIS_DIRECTORY,
    ):
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Completed-day policy
#
# Moved here from the retired root ``tracker_config`` module. Only completed
# local calendar days are processed by default; the current day is incomplete.
# ---------------------------------------------------------------------------

LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo

EXCLUDE_CURRENT_DAY_BY_DEFAULT = True


def today_local() -> date:
    """Return today's local calendar date."""
    return datetime.now(LOCAL_TIMEZONE).date()


def latest_completed_date() -> date:
    """Return the latest fully completed calendar day (yesterday, local)."""
    return today_local() - timedelta(days=1)


def is_completed_date(target_date: date, include_today: bool = False) -> bool:
    """Return whether a date is eligible for normal processing."""
    if include_today:
        return target_date <= today_local()
    return target_date <= latest_completed_date()


def validate_completed_date(
    target_date: date,
    include_today: bool = False,
) -> None:
    """Raise when a date violates the completed-day rule."""
    if is_completed_date(target_date, include_today=include_today):
        return
    raise ValueError(
        f"{target_date.isoformat()} is the current day or a future date "
        "and is excluded by default. "
        "Use --include-today to explicitly include today's data."
    )
