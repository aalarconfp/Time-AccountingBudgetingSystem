"""Portable export contract between Desktop Tracker Collector and System Tracker.

This module is the single source of truth for the export package layout and
the manifest schema. It is intentionally free of third-party imports so that
System Tracker can vendor a copy for its importer without taking a dependency
on this project.

Versioning
----------
EXPORT_CONTRACT_VERSION changes only when the package layout or the manifest
schema changes in a way that requires the System Tracker importer to be
updated. The RAW/FACT/DAILY schema versions change when the corresponding CSV
column contract changes.
"""

from __future__ import annotations

from datetime import date, timedelta

from config.settings import DESKTOP_DEVICE

# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

GENERATOR = "Desktop Tracker Collector"
COLLECTOR_VERSION = "1.0.0"

EXPORT_CONTRACT_VERSION = "1.0"

# The collector only ever produces one source/device.
SOURCE = "ActivityWatch"
DEVICE_KEY = "desktop"
# Configured per installation (config/settings.py); it must match the
# collector's device hostname.
DEVICE_HOSTNAME = DESKTOP_DEVICE

# --------------------------------------------------------------------------
# CSV schema contracts (mirror System Tracker)
# --------------------------------------------------------------------------

RAW_SCHEMA_VERSION = "1.0"
FACT_SCHEMA_VERSION = "1.0"
DAILY_SCHEMA_VERSION = "1.0"

RAW_ACTIVITYWATCH_COLUMNS = (
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
)

FACT_TIME_COLUMNS = (
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
)

# --------------------------------------------------------------------------
# Package layout
# --------------------------------------------------------------------------

MANIFEST_NAME = "manifest.json"
METADATA_NAME = "metadata.json"
README_NAME = "README.txt"

# Canonical relative subtrees inside both the collector `output/` directory and
# the exported package. System Tracker consumes the same layout.
RAW_SUBPATH = "Raw/ActivityWatch/" + DEVICE_HOSTNAME
FACT_SUBPATH = "Fact/Time/ActivityWatch/" + DEVICE_HOSTNAME
DAILY_SUBPATH = "Daily/Time/ActivityWatch/" + DEVICE_HOSTNAME
VALIDATION_SUBPATH = "Validation"
COLLECTION_SUBPATH = "Collection"

RAW_FILE_PREFIX = "Raw_ActivityWatch_"
FACT_FILE_PREFIX = "Fact_Time_"
DAILY_FILE_PREFIX = "Daily_Time_"
CSV_SUFFIX = ".csv"

VALIDATION_PASS = "PASS"
VALIDATION_FAIL = "FAIL"
VALIDATION_SKIPPED = "SKIPPED"


def package_name(start: date, end: date) -> str:
    """Return the canonical export directory name for a period."""
    return f"{DEVICE_HOSTNAME}__{start.isoformat()}__{end.isoformat()}"


def inclusive_dates(start: date, end: date) -> list[date]:
    """Return every calendar date in an inclusive range."""
    if end < start:
        raise ValueError("end date precedes start date")
    span = (end - start).days
    return [start + timedelta(days=offset) for offset in range(span + 1)]


def raw_filename(target: date) -> str:
    """Return the Raw_ActivityWatch CSV filename for a date."""
    return f"{RAW_FILE_PREFIX}{target.isoformat()}{CSV_SUFFIX}"


def fact_filename(target: date) -> str:
    """Return the Fact_Time CSV filename for a date."""
    return f"{FACT_FILE_PREFIX}{target.isoformat()}{CSV_SUFFIX}"


def daily_filename(target: date) -> str:
    """Return the Daily_Time CSV filename for a date."""
    return f"{DAILY_FILE_PREFIX}{target.isoformat()}{CSV_SUFFIX}"


def validation_report_name(start: date, end: date) -> str:
    """Return the Fact_Time validation report filename for a period."""
    return (
        f"Fact_Time_Validation_"
        f"{start.isoformat()}_{end.isoformat()}.txt"
    )


def collection_manifest_name(start: date, end: date) -> str:
    """Return the in-project collection manifest filename for a period."""
    return (
        f"Collection_Manifest_"
        f"{start.isoformat()}_{end.isoformat()}.json"
    )


def is_compatible_contract(version: str) -> bool:
    """Return whether an export was produced by a compatible contract.

    Compatibility is by major version. ``1.x`` packages are importable by a
    ``1.y`` importer.
    """
    try:
        major = int(str(version).split(".", 1)[0])
        expected = int(EXPORT_CONTRACT_VERSION.split(".", 1)[0])
    except (AttributeError, ValueError):
        return False
    return major == expected
