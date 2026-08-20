# integrated_daily_time_builder.py

"""Build the canonical integrated daily activity-time dataset.

The integration layer combines source-specific Daily_Time datasets from:

    - ActivityWatch / ASUS laptop
    - ActivityWatch / desktop
    - Apple Screen Time / iPhone
    - Habit / OffDevice

Source-specific Raw, Fact_Time, and Daily_Time datasets are never modified.

The integrated layer:
    1. validates source coverage,
    2. reads source-specific Daily_Time records,
    3. preserves source identity,
    4. validates source-specific taxonomies,
    5. optionally classifies Uncategorized ActivityWatch time,
    6. adds manual integrated records,
    7. optionally calculates a residual only for a single-source build,
    8. writes one integrated dataset per completed calendar date.

Important:
Multiple activity trackers can overlap in real time. Therefore a multi-source
integration must not manufacture a 24-hour residual from:

    laptop + desktop + iPhone + habit

The integrated dataset represents observed/declared activity records across
sources, not a mutually exclusive 24-hour clock ledger.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from config.sources import SOURCE_DEFINITIONS
from config.taxonomy import is_supported_category_path
from config.tracker_config import (
    DAILY_DIRECTORY,
    DEFAULT_TIMEZONE,
    INTEGRATED_DIRECTORY,
    PROJECT_ROOT,
)


SECONDS_PER_DAY = 24 * 60 * 60
CSV_ENCODING = "utf-8-sig"

MANUAL_INPUT_PATH = (
    PROJECT_ROOT
    / "input"
    / "Integrated"
    / "Manual_Adjustments.csv"
)

CLASSIFICATION_INPUT_PATH = (
    PROJECT_ROOT
    / "input"
    / "Integrated"
    / "Classification_Weights.csv"
)


@dataclass(frozen=True)
class DailyRecord:
    """Represent one integrated daily activity record."""

    date: str
    category: str
    subcategory: str
    duration_sec: float
    event_count: int
    source: str
    source_name: str
    source_device: str
    source_type: str
    allocation_type: str
    device_count: int
    devices: str
    contexts: str


@dataclass(frozen=True)
class ManualRecord:
    """Represent one manual integrated-time record."""

    date: str
    category: str
    subcategory: str
    duration_sec: float
    note: str


@dataclass(frozen=True)
class ClassificationWeight:
    """Represent one weighted Uncategorized allocation."""

    device: str
    category: str
    subcategory: str
    allocation_pct: float
    note: str


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build Integrated Daily Time from source-specific "
            "Daily_Time datasets."
        )
    )

    parser.add_argument(
        "--date",
        dest="target_date",
        help="Completed calendar date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--start-date",
        help="First completed date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--end-date",
        help="Last completed date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCE_DEFINITIONS),
        help=(
            "Source to include. May be specified more than once. "
            "Defaults to all configured sources."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATED_DIRECTORY,
        help="Integrated output directory.",
    )

    parser.add_argument(
        "--manual-input",
        type=Path,
        default=MANUAL_INPUT_PATH,
        help="CSV containing manual integrated-time records.",
    )

    parser.add_argument(
        "--classification-input",
        type=Path,
        default=CLASSIFICATION_INPUT_PATH,
        help=(
            "CSV containing weighted allocations for Uncategorized "
            "observed time."
        ),
    )

    return parser.parse_args()


def parse_date(value: str) -> date:
    """Parse an ISO calendar date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def get_project_timezone() -> ZoneInfo:
    """Return the configured project timezone."""
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load project timezone "
            f"'{DEFAULT_TIMEZONE}'."
        ) from exc


def get_latest_completed_date() -> date:
    """Return yesterday in the configured project timezone."""
    return (
        datetime.now(get_project_timezone()).date()
        - timedelta(days=1)
    )


def resolve_date_range(
    args: argparse.Namespace,
) -> tuple[date, date]:
    """Resolve the requested completed-date range."""
    latest_completed = get_latest_completed_date()

    if args.target_date:
        target = parse_date(args.target_date)

        if target > latest_completed:
            raise ValueError(
                f"Date {target} is not a completed day. "
                f"The latest completed date is "
                f"{latest_completed}."
            )

        return target, target

    if args.start_date or args.end_date:
        start = (
            parse_date(args.start_date)
            if args.start_date
            else latest_completed
        )
        end = (
            parse_date(args.end_date)
            if args.end_date
            else latest_completed
        )
    else:
        start = latest_completed
        end = latest_completed

    if end < start:
        raise ValueError(
            f"End date {end} cannot be before start date {start}."
        )

    if end > latest_completed:
        raise ValueError(
            f"End date {end} is not a completed day. "
            f"The latest completed date is "
            f"{latest_completed}."
        )

    return start, end


def get_integrated_sources(
    requested_sources: list[str] | None,
) -> list[str]:
    """Return selected configured sources."""
    if requested_sources:
        return sorted(set(requested_sources))

    return sorted(SOURCE_DEFINITIONS)


def get_source_definition(
    source_name: str,
):
    """Return a configured source definition."""
    try:
        return SOURCE_DEFINITIONS[source_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown configured source: {source_name}"
        ) from exc


def get_daily_path(
    source_name: str,
    target_date: date,
) -> Path:
    """Return the canonical Daily_Time path for a configured source."""
    definition = get_source_definition(source_name)
    source_type = definition.source.value

    if source_type == "ActivityWatch":
        if not definition.device:
            raise ValueError(
                f"ActivityWatch source '{source_name}' "
                "does not define a device."
            )

        directory = (
            DAILY_DIRECTORY
            / "Time"
            / "ActivityWatch"
            / definition.device
        )

    elif source_type == "AppleScreenTime":
        directory = (
            DAILY_DIRECTORY
            / "Time"
            / "AppleScreenTime"
            / (
                definition.device
                if definition.device
                else "iPhone"
            )
        )

    elif source_type == "Habit":
        directory = (
            DAILY_DIRECTORY
            / "Time"
            / "Habit"
            / "OffDevice"
        )

    else:
        raise ValueError(
            f"Unsupported Daily_Time source type "
            f"'{source_type}' for '{source_name}'."
        )

    return (
        directory
        / f"Daily_Time_{target_date.isoformat()}.csv"
    )


def read_csv(
    path: Path,
) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file."""
    with path.open(
        mode="r",
        newline="",
        encoding=CSV_ENCODING,
    ) as file:
        return list(csv.DictReader(file))


def parse_float(
    value: str | None,
    field: str,
    path: Path,
) -> float:
    """Parse a numeric CSV field."""
    try:
        return float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid {field} '{value}' in {path}."
        ) from exc


def parse_int(
    value: str | None,
    field: str,
    path: Path,
) -> int:
    """Parse an integer CSV field."""
    try:
        return int(float(value or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid {field} '{value}' in {path}."
        ) from exc


def validate_daily_row(
    row: dict[str, str],
    path: Path,
    source_name: str,
) -> None:
    """Validate one source-specific Daily_Time row."""
    required = (
        "Date",
        "Category",
        "Subcategory",
        "Duration_sec",
        "Event_Count",
    )

    missing = [
        field
        for field in required
        if field not in row
    ]

    if missing:
        raise ValueError(
            f"Missing columns {missing} in {path}."
        )

    category = (row.get("Category") or "").strip()
    subcategory = (row.get("Subcategory") or "").strip()

    if not category:
        raise ValueError(
            f"Empty Category in {path}."
        )

    definition = get_source_definition(source_name)
    source_type = definition.source.value

    if source_type in {"Habit", "AppleScreenTime"}:
        return

    if category == "Uncategorized":
        if subcategory:
            raise ValueError(
                "Uncategorized must not have a subcategory "
                f"in {path}: {category} > {subcategory}"
            )
        return

    if not is_supported_category_path(
        category,
        subcategory,
    ):
        raise ValueError(
            "Unsupported ActivityWatch taxonomy path in "
            f"{path}: {category} > {subcategory}"
        )


def read_daily_records(
    source_name: str,
    target_date: date,
) -> list[DailyRecord]:
    """Read one source's Daily_Time dataset."""
    path = get_daily_path(
        source_name,
        target_date,
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Missing Daily_Time dataset: {path}"
        )

    rows = read_csv(path)
    definition = get_source_definition(source_name)

    records: list[DailyRecord] = []

    for row in rows:
        validate_daily_row(
            row,
            path,
            source_name,
        )

        row_date = (row.get("Date") or "").strip()

        if row_date:
            parsed_row_date = parse_date(row_date)

            if parsed_row_date != target_date:
                raise ValueError(
                    f"Daily_Time row date {parsed_row_date} "
                    f"does not match requested date "
                    f"{target_date} in {path}."
                )

        records.append(
            DailyRecord(
                date=target_date.isoformat(),
                category=(row.get("Category") or "").strip(),
                subcategory=(
                    row.get("Subcategory") or ""
                ).strip(),
                duration_sec=parse_float(
                    row.get("Duration_sec"),
                    "Duration_sec",
                    path,
                ),
                event_count=parse_int(
                    row.get("Event_Count"),
                    "Event_Count",
                    path,
                ),
                source=definition.source.value,
                source_name=source_name,
                source_device=definition.device or "",
                source_type=definition.source.value,
                allocation_type=(
                    row.get("Allocation_Type")
                    or "Observed"
                ).strip()
                or "Observed",
                device_count=1,
                devices=definition.device or "",
                contexts=definition.context,
            )
        )

    return records


def ensure_manual_template(
    path: Path,
) -> None:
    """Create the manual-adjustment template if absent."""
    if path.exists():
        return

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        mode="w",
        newline="",
        encoding=CSV_ENCODING,
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "Date",
                "Category",
                "Subcategory",
                "Duration_sec",
                "Note",
            ],
        )
        writer.writeheader()


def ensure_classification_template(
    path: Path,
) -> None:
    """Create the weighted-classification template if absent."""
    if path.exists():
        return

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        mode="w",
        newline="",
        encoding=CSV_ENCODING,
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "Device",
                "Category",
                "Subcategory",
                "Allocation_Pct",
                "Note",
            ],
        )
        writer.writeheader()


def read_manual_records(
    path: Path,
    target_date: date,
) -> list[ManualRecord]:
    """Read manual records for one date."""
    if not path.exists():
        return []

    rows = read_csv(path)
    records: list[ManualRecord] = []

    for row in rows:
        row_date = (row.get("Date") or "").strip()

        if not row_date:
            continue

        if parse_date(row_date) != target_date:
            continue

        category = (row.get("Category") or "").strip()
        subcategory = (
            row.get("Subcategory") or ""
        ).strip()

        if not category:
            raise ValueError(
                f"Manual record has no Category in {path}."
            )

        if category != "Off-Device":
            if not is_supported_category_path(
                category,
                subcategory,
            ):
                raise ValueError(
                    "Unsupported manual taxonomy path: "
                    f"{category} > {subcategory}"
                )

        duration_sec = parse_float(
            row.get("Duration_sec"),
            "Duration_sec",
            path,
        )

        if duration_sec < 0:
            raise ValueError(
                f"Manual duration cannot be negative in {path}."
            )

        records.append(
            ManualRecord(
                date=row_date,
                category=category,
                subcategory=subcategory,
                duration_sec=duration_sec,
                note=(row.get("Note") or "").strip(),
            )
        )

    return records


def read_classification_weights(
    path: Path,
) -> list[ClassificationWeight]:
    """Read weighted allocations for Uncategorized time."""
    if not path.exists():
        return []

    rows = read_csv(path)
    weights: list[ClassificationWeight] = []

    for row in rows:
        device = (row.get("Device") or "").strip()
        category = (row.get("Category") or "").strip()
        subcategory = (
            row.get("Subcategory") or ""
        ).strip()

        if not category:
            raise ValueError(
                f"Classification row has no Category in {path}."
            )

        if category == "Uncategorized":
            raise ValueError(
                "Classification target cannot be Uncategorized "
                f"in {path}."
            )

        if not is_supported_category_path(
            category,
            subcategory,
        ):
            raise ValueError(
                "Unsupported classification target: "
                f"{category} > {subcategory}"
            )

        allocation_pct = parse_float(
            row.get("Allocation_Pct"),
            "Allocation_Pct",
            path,
        )

        if allocation_pct <= 0:
            raise ValueError(
                "Allocation_Pct must be greater than zero."
            )

        if allocation_pct > 100:
            raise ValueError(
                "Allocation_Pct cannot exceed 100."
            )

        weights.append(
            ClassificationWeight(
                device=device,
                category=category,
                subcategory=subcategory,
                allocation_pct=allocation_pct,
                note=(row.get("Note") or "").strip(),
            )
        )

    return weights


def validate_classification_weights(
    weights: list[ClassificationWeight],
    source_names: list[str],
) -> None:
    """Validate weighted allocations against selected ActivityWatch devices."""
    if not weights:
        return

    selected_devices = {
        get_source_definition(name).device
        for name in source_names
        if get_source_definition(name).device
    }

    grouped: dict[
        str,
        list[ClassificationWeight],
    ] = defaultdict(list)

    for weight in weights:
        if (
            weight.device
            and weight.device not in selected_devices
        ):
            raise ValueError(
                "Classification weight references an unselected "
                f"device: {weight.device}"
            )

        key = weight.device or "*"
        grouped[key].append(weight)

    for key, group in grouped.items():
        total = sum(
            weight.allocation_pct
            for weight in group
        )

        if abs(total - 100.0) > 0.001:
            label = (
                "ALL DEVICES"
                if key == "*"
                else key
            )

            raise ValueError(
                f"Classification weights for {label} "
                f"total {total:.3f}%; expected 100%."
            )


def apply_classification_weights(
    records: list[DailyRecord],
    weights: list[ClassificationWeight],
) -> tuple[list[DailyRecord], float, float]:
    """Apply weighted allocations to ActivityWatch Uncategorized time."""
    if not weights:
        return records, 0.0, 0.0

    all_device_weights = [
        weight
        for weight in weights
        if not weight.device
    ]

    device_weights: dict[
        str,
        list[ClassificationWeight],
    ] = defaultdict(list)

    for weight in weights:
        if weight.device:
            device_weights[weight.device].append(weight)

    uncategorized_by_device: dict[
        str,
        list[DailyRecord],
    ] = defaultdict(list)

    non_uncategorized: list[DailyRecord] = []

    for record in records:
        if (
            record.category == "Uncategorized"
            and record.source_type == "ActivityWatch"
        ):
            uncategorized_by_device[
                record.source_device
            ].append(record)
        else:
            non_uncategorized.append(record)

    original_uncategorized = sum(
        record.duration_sec
        for records_for_device
        in uncategorized_by_device.values()
        for record in records_for_device
    )

    classified_seconds = 0.0
    result = list(non_uncategorized)

    for (
        device,
        device_records,
    ) in uncategorized_by_device.items():
        device_duration = sum(
            record.duration_sec
            for record in device_records
        )

        applicable = device_weights.get(device)

        if not applicable:
            applicable = all_device_weights

        if not applicable:
            result.extend(device_records)
            continue

        representative = device_records[0]

        for weight in applicable:
            allocated_seconds = (
                device_duration
                * weight.allocation_pct
                / 100.0
            )

            if allocated_seconds <= 0:
                continue

            result.append(
                DailyRecord(
                    date=representative.date,
                    category=weight.category,
                    subcategory=weight.subcategory,
                    duration_sec=allocated_seconds,
                    event_count=0,
                    source=representative.source,
                    source_name=representative.source_name,
                    source_device=representative.source_device,
                    source_type=representative.source_type,
                    allocation_type="Classified",
                    device_count=1,
                    devices=device,
                    contexts=representative.contexts,
                )
            )

            classified_seconds += allocated_seconds

    return (
        result,
        original_uncategorized,
        classified_seconds,
    )


def aggregate_records(
    records: Iterable[DailyRecord],
) -> list[DailyRecord]:
    """Aggregate records without merging distinct configured sources."""
    grouped: dict[
        tuple[str, str, str, str, str],
        dict[str, object],
    ] = {}

    for record in records:
        key = (
            record.source_name,
            record.category,
            record.subcategory,
            record.allocation_type,
            record.source_device,
        )

        if key not in grouped:
            grouped[key] = {
                "date": record.date,
                "duration_sec": 0.0,
                "event_count": 0,
                "devices": set(),
                "contexts": set(),
                "source": record.source,
                "source_type": record.source_type,
            }

        item = grouped[key]

        item["duration_sec"] = (
            float(item["duration_sec"])
            + record.duration_sec
        )

        item["event_count"] = (
            int(item["event_count"])
            + record.event_count
        )

        devices = item["devices"]
        contexts = item["contexts"]

        if isinstance(devices, set) and record.devices:
            devices.add(record.devices)

        if isinstance(contexts, set) and record.contexts:
            contexts.add(record.contexts)

    result: list[DailyRecord] = []

    for (
        source_name,
        category,
        subcategory,
        allocation_type,
        source_device,
    ), item in grouped.items():
        devices = item["devices"]
        contexts = item["contexts"]

        result.append(
            DailyRecord(
                date=str(item["date"]),
                category=category,
                subcategory=subcategory,
                duration_sec=float(
                    item["duration_sec"]
                ),
                event_count=int(
                    item["event_count"]
                ),
                source=str(item["source"]),
                source_name=source_name,
                source_device=source_device,
                source_type=str(
                    item["source_type"]
                ),
                allocation_type=allocation_type,
                device_count=len(devices),
                devices=", ".join(
                    sorted(devices)
                ),
                contexts=", ".join(
                    sorted(contexts)
                ),
            )
        )

    return result


def convert_manual_records(
    records: list[ManualRecord],
) -> list[DailyRecord]:
    """Convert manual records to integrated records."""
    return [
        DailyRecord(
            date=record.date,
            category=record.category,
            subcategory=record.subcategory,
            duration_sec=record.duration_sec,
            event_count=0,
            source="Manual",
            source_name="manual",
            source_device="",
            source_type="Manual",
            allocation_type="Manual",
            device_count=0,
            devices="",
            contexts="",
        )
        for record in records
    ]


def calculate_total(
    records: Iterable[DailyRecord],
) -> float:
    """Calculate total duration."""
    return sum(
        record.duration_sec
        for record in records
    )


def build_residual(
    target_date: date,
    observed_seconds: float,
    manual_seconds: float,
) -> DailyRecord | None:
    """Create residual Off-Device time."""
    remaining = (
        SECONDS_PER_DAY
        - observed_seconds
        - manual_seconds
    )

    if remaining <= 0.001:
        return None

    return DailyRecord(
        date=target_date.isoformat(),
        category="Off-Device",
        subcategory="",
        duration_sec=remaining,
        event_count=0,
        source="System",
        source_name="system",
        source_device="",
        source_type="System",
        allocation_type="Residual",
        device_count=0,
        devices="",
        contexts="",
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


def write_output(
    records: list[DailyRecord],
    target_date: date,
    output_path: Path,
) -> None:
    """Write integrated records to CSV."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "Date",
        "Category",
        "Subcategory",
        "Duration_sec",
        "Duration_min",
        "Duration_hours",
        "Event_Count",
        "Source",
        "Source_Name",
        "Source_Type",
        "Source_Device",
        "Allocation_Type",
        "Device_Count",
        "Devices",
        "Contexts",
    ]

    with output_path.open(
        mode="w",
        newline="",
        encoding=CSV_ENCODING,
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for record in records:
            writer.writerow(
                {
                    "Date": target_date.isoformat(),
                    "Category": record.category,
                    "Subcategory": record.subcategory,
                    "Duration_sec": round(
                        record.duration_sec,
                        3,
                    ),
                    "Duration_min": round(
                        record.duration_sec / 60,
                        3,
                    ),
                    "Duration_hours": round(
                        record.duration_sec / 3600,
                        6,
                    ),
                    "Event_Count": record.event_count,
                    "Source": record.source,
                    "Source_Name": record.source_name,
                    "Source_Type": record.source_type,
                    "Source_Device": record.source_device,
                    "Allocation_Type": (
                        record.allocation_type
                    ),
                    "Device_Count": record.device_count,
                    "Devices": record.devices,
                    "Contexts": record.contexts,
                }
            )


def build_date(
    target_date: date,
    source_names: list[str],
    manual_path: Path,
    classification_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Build one fully covered integrated date."""
    missing_sources: list[tuple[str, Path]] = []

    for source_name in source_names:
        path = get_daily_path(
            source_name,
            target_date,
        )

        if not path.exists():
            missing_sources.append(
                (
                    source_name,
                    path,
                )
            )

    print()
    print(f"--- {target_date} ---")

    if missing_sources:
        print(
            "STATUS              : INCOMPLETE SOURCE COVERAGE"
        )

        for source_name, path in missing_sources:
            print(
                f"Missing source       : {source_name}"
            )
            print(
                f"Missing Daily_Time   : {path}"
            )

        print(
            "Off-Device residual  : NOT CALCULATED"
        )
        print(
            "24-hour balance      : NOT VALID"
        )

        return {
            "built": False,
            "complete": False,
            "observed": 0.0,
            "manual": 0.0,
            "allocated": 0.0,
            "rows": 0,
            "uncategorized": 0.0,
            "classified": 0.0,
            "overage": 0.0,
        }

    observed_records: list[DailyRecord] = []

    for source_name in source_names:
        source_records = read_daily_records(
            source_name,
            target_date,
        )

        print(
            f"{source_name:20s}: "
            f"{len(source_records):>6} rows | "
            f"{format_duration(calculate_total(source_records))}"
        )

        observed_records.extend(
            source_records
        )

    weights = read_classification_weights(
        classification_path
    )

    validate_classification_weights(
        weights,
        source_names,
    )

    (
        classified_records,
        original_uncategorized,
        classified_seconds,
    ) = apply_classification_weights(
        observed_records,
        weights,
    )

    observed_records = aggregate_records(
        classified_records
    )

    manual_records = read_manual_records(
        manual_path,
        target_date,
    )

    manual_integrated = convert_manual_records(
        manual_records
    )

    observed_seconds = calculate_total(
        observed_records
    )

    manual_seconds = calculate_total(
        manual_integrated
    )

    combined_seconds = (
        observed_seconds
        + manual_seconds
    )

    multi_source = len(source_names) > 1

    residual: DailyRecord | None = None

    if multi_source:
        overage = max(
            combined_seconds - SECONDS_PER_DAY,
            0.0,
        )

        print(
            "Residual Off-Device : NOT CALCULATED "
            "(multi-source)"
        )

        if overage > 0.001:
            print(
                "24-hour check       : OVERLAP DETECTED "
                f"(+{format_duration(overage)})"
            )
        else:
            print(
                "24-hour check       : NOT APPLICABLE "
                "(multi-source activity)"
            )

    else:
        overage = (
            combined_seconds
            - SECONDS_PER_DAY
        )

        if overage <= 0.001:
            residual = build_residual(
                target_date,
                observed_seconds,
                manual_seconds,
            )

            print(
                "Residual Off-Device : "
                f"{format_duration(residual.duration_sec)}"
                if residual
                else
                "Residual Off-Device : 0m"
            )
        else:
            print(
                "Residual Off-Device : NOT CALCULATED"
            )
            print(
                "24-hour check       : OVER 24 HOURS "
                f"BY {format_duration(overage)}"
            )

    records = [
        *observed_records,
        *manual_integrated,
    ]

    if residual:
        records.append(residual)

    allocated_seconds = calculate_total(records)

    output_path = (
        output_dir
        / (
            "Integrated_Daily_Time_"
            f"{target_date.isoformat()}.csv"
        )
    )

    output_records = sorted(
        records,
        key=lambda record: (
            record.category,
            record.subcategory,
            record.source_name,
            record.allocation_type,
        ),
    )

    write_output(
        output_records,
        target_date,
        output_path,
    )

    print(
        "Observed time       : "
        f"{format_duration(observed_seconds)}"
    )
    print(
        "Original Uncategorized: "
        f"{format_duration(original_uncategorized)}"
    )
    print(
        "Classified time     : "
        f"{format_duration(classified_seconds)}"
    )
    print(
        "Manual time         : "
        f"{format_duration(manual_seconds)}"
    )
    print(
        "Allocated total     : "
        f"{format_duration(allocated_seconds)}"
    )
    print(
        "Integrated rows     : "
        f"{len(records)}"
    )
    print(
        f"Output              : {output_path}"
    )

    if multi_source:
        status = "PASS: MULTI-SOURCE INTEGRATION"
    elif overage > 0.001:
        status = "WARNING: OVER 24 HOURS"
    else:
        status = "PASS"

    print(
        f"Status              : {status}"
    )

    return {
        "built": True,
        "complete": True,
        "observed": observed_seconds,
        "manual": manual_seconds,
        "allocated": allocated_seconds,
        "rows": len(records),
        "uncategorized": original_uncategorized,
        "classified": classified_seconds,
        "overage": max(overage, 0.0),
        "multi_source": multi_source,
    }


def main() -> int:
    """Run the Integrated Daily Time builder."""
    args = parse_arguments()

    try:
        start_date, end_date = resolve_date_range(args)

        source_names = get_integrated_sources(
            args.source
        )

        if not source_names:
            raise ValueError(
                "No configured integration sources are available."
            )

        ensure_manual_template(
            args.manual_input
        )

        ensure_classification_template(
            args.classification_input
        )

        print("# Integrated Daily Time Builder")
        print()
        print(
            "Sources  : "
            + ", ".join(source_names)
        )
        print(
            f"Dates    : {start_date} → {end_date}"
        )
        print(
            "Mode     : COMPLETED DAYS ONLY"
        )
        print()
        print("=== Configuration ===")
        print(
            f"Manual input         : "
            f"{args.manual_input}"
        )
        print(
            f"Classification input : "
            f"{args.classification_input}"
        )
        print(
            f"Output               : "
            f"{args.output_dir}"
        )

        dates_checked = 0
        dates_built = 0
        incomplete_dates = 0
        overage_dates = 0
        multi_source_dates = 0

        total_observed = 0.0
        total_manual = 0.0
        total_allocated = 0.0
        total_rows = 0
        total_uncategorized = 0.0
        total_classified = 0.0

        current_date = start_date

        while current_date <= end_date:
            dates_checked += 1

            result = build_date(
                target_date=current_date,
                source_names=source_names,
                manual_path=args.manual_input,
                classification_path=(
                    args.classification_input
                ),
                output_dir=args.output_dir,
            )

            if not result["complete"]:
                incomplete_dates += 1

            elif result["built"]:
                dates_built += 1

                total_observed += float(
                    result["observed"]
                )

                total_manual += float(
                    result["manual"]
                )

                total_allocated += float(
                    result["allocated"]
                )

                total_rows += int(
                    result["rows"]
                )

                total_uncategorized += float(
                    result["uncategorized"]
                )

                total_classified += float(
                    result["classified"]
                )

                if bool(
                    result.get("multi_source", False)
                ):
                    multi_source_dates += 1

                if (
                    not bool(
                        result.get(
                            "multi_source",
                            False,
                        )
                    )
                    and float(result["overage"]) > 0.001
                ):
                    overage_dates += 1

            current_date += timedelta(days=1)

        print()
        print("=" * 60)
        print(
            "=== Integrated Daily Time Build Summary ==="
        )
        print(
            f"Dates checked          : "
            f"{dates_checked}"
        )
        print(
            f"Dates built            : "
            f"{dates_built}"
        )
        print(
            f"Incomplete dates       : "
            f"{incomplete_dates}"
        )
        print(
            f"Integrated rows        : "
            f"{total_rows}"
        )
        print(
            "Observed integrated    : "
            f"{format_duration(total_observed)}"
        )
        print(
            "Uncategorized pool     : "
            f"{format_duration(total_uncategorized)}"
        )
        print(
            "Classified from pool   : "
            f"{format_duration(total_classified)}"
        )
        print(
            "Manual time            : "
            f"{format_duration(total_manual)}"
        )
        print(
            "Allocated total        : "
            f"{format_duration(total_allocated)}"
        )
        print(
            f"Multi-source dates     : "
            f"{multi_source_dates}"
        )
        print(
            f"Over-24h dates         : "
            f"{overage_dates}"
        )

        if incomplete_dates:
            print()
            print(
                "RESULT: INTEGRATED BUILD INCOMPLETE."
            )
            print(
                "Missing source data must be resolved "
                "before the date can be integrated."
            )
            return 1

        if overage_dates:
            print()
            print(
                "RESULT: INTEGRATED BUILD PASSED "
                "WITH WARNINGS."
            )
            print(
                "Single-source dates exceeded 24 hours."
            )
            return 0

        print()
        print(
            "RESULT: INTEGRATED DAILY TIME BUILD PASSED."
        )

        return 0

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())