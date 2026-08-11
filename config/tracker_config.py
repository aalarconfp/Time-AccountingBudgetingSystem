"""Central project configuration.

This module defines stable project-level paths and defaults. Source-specific
definitions live in ``config.sources`` and taxonomy definitions live in
``config.taxonomy``.
"""

from pathlib import Path

from config.sources import ASUS_LAPTOP, DESKTOP, HABIT, IPHONE, SourceDefinition


PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INPUT_DIRECTORY = PROJECT_ROOT / "input"
DOCUMENTATION_DIRECTORY = PROJECT_ROOT / "documentation"
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
