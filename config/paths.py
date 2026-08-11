# config/paths.py

from __future__ import annotations

from pathlib import Path

from config.sources import SourceType


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_ROOT = PROJECT_ROOT / "input"
OUTPUT_ROOT = PROJECT_ROOT / "output"

ACTIVITYWATCH_INPUT_ROOT = INPUT_ROOT / "ActivityWatch"
APPLE_SCREEN_TIME_INPUT_ROOT = INPUT_ROOT / "AppleScreenTime"
HABIT_INPUT_ROOT = INPUT_ROOT / "Habit"

RAW_ROOT = OUTPUT_ROOT / "Raw"
FACT_ROOT = OUTPUT_ROOT / "Fact"
DAILY_ROOT = OUTPUT_ROOT / "Daily"
ANALYSIS_ROOT = OUTPUT_ROOT / "Analysis"

ACTIVITYWATCH_RAW_ROOT = RAW_ROOT / "ActivityWatch"
APPLE_SCREEN_TIME_RAW_ROOT = RAW_ROOT / "AppleScreenTime"
HABIT_RAW_ROOT = RAW_ROOT / "Habit"

FACT_TIME_ROOT = FACT_ROOT / "Time"
DAILY_TIME_ROOT = DAILY_ROOT / "Time"
ANALYSIS_TIME_ROOT = ANALYSIS_ROOT / "Time"


def get_source_input_root(source: SourceType) -> Path:
    """Return the canonical input directory for a source."""
    roots = {
        SourceType.ACTIVITYWATCH: ACTIVITYWATCH_INPUT_ROOT,
        SourceType.APPLE_SCREEN_TIME: APPLE_SCREEN_TIME_INPUT_ROOT,
        SourceType.HABIT: HABIT_INPUT_ROOT,
    }

    try:
        return roots[source]
    except KeyError as exc:
        raise ValueError(f"Unsupported source: {source!r}") from exc


def get_source_raw_root(source: SourceType) -> Path:
    """Return the canonical raw-output directory for a source."""
    roots = {
        SourceType.ACTIVITYWATCH: ACTIVITYWATCH_RAW_ROOT,
        SourceType.APPLE_SCREEN_TIME: APPLE_SCREEN_TIME_RAW_ROOT,
        SourceType.HABIT: HABIT_RAW_ROOT,
    }

    try:
        return roots[source]
    except KeyError as exc:
        raise ValueError(f"Unsupported source: {source!r}") from exc


def get_fact_time_root() -> Path:
    """Return the canonical Fact_Time directory."""
    return FACT_TIME_ROOT


def get_daily_time_root() -> Path:
    """Return the canonical Daily_Time directory."""
    return DAILY_TIME_ROOT


def get_analysis_time_root() -> Path:
    """Return the canonical time-analysis directory."""
    return ANALYSIS_TIME_ROOT


def get_all_project_directories() -> tuple[Path, ...]:
    """Return directories required by the multi-source tracker."""
    return (
        INPUT_ROOT,
        OUTPUT_ROOT,
        ACTIVITYWATCH_INPUT_ROOT,
        APPLE_SCREEN_TIME_INPUT_ROOT,
        HABIT_INPUT_ROOT,
        RAW_ROOT,
        ACTIVITYWATCH_RAW_ROOT,
        APPLE_SCREEN_TIME_RAW_ROOT,
        HABIT_RAW_ROOT,
        FACT_ROOT,
        FACT_TIME_ROOT,
        DAILY_ROOT,
        DAILY_TIME_ROOT,
        ANALYSIS_ROOT,
        ANALYSIS_TIME_ROOT,
    )


def ensure_project_directories() -> None:
    """Create the canonical project directories when they do not exist."""
    for directory in get_all_project_directories():
        directory.mkdir(parents=True, exist_ok=True)