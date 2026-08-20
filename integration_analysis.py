# integration_analysis.py

"""Analyze integrated multi-source activity coverage.

This analysis intentionally treats Integrated Daily Time as an observed
activity dataset rather than a mutually exclusive 24-hour accounting ledger.

Primary metrics:

    Recorded Activity
        Sum of durations reported by the selected integrated sources.

    Unaccounted Time
        24 hours minus Recorded Activity when Recorded Activity <= 24 hours.

    Overlap Excess
        Recorded Activity minus 24 hours when Recorded Activity > 24 hours.

    Coverage %
        Recorded Activity / 24 hours, capped at 100%.

The analysis target is configurable and defaults to:

    Unaccounted Time <= 3 hours

The resulting metrics are intended for aggregate pattern recognition and
80/20 decision-making rather than minute-perfect personal accounting.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from config.tracker_config import (
    DEFAULT_TIMEZONE,
    INTEGRATED_DIRECTORY,
    PROJECT_ROOT,
)


SECONDS_PER_DAY = 24 * 60 * 60
DEFAULT_UNACCOUNTED_TARGET_HOURS = 3.0
CSV_ENCODING = "utf-8-sig"

DEFAULT_OUTPUT_DIRECTORY = (
    PROJECT_ROOT / "output" / "Integrated" / "Analysis"
)


@dataclass(frozen=True)
class SourceMetric:
    """Represent one source's daily duration."""

    source_name: str
    source_type: str
    duration_sec: float


@dataclass(frozen=True)
class DailyAnalysis:
    """Represent one day's integration analysis."""

    date: date
    weekday: str
    day_type: str

    recorded_sec: float
    unaccounted_sec: float
    overlap_excess_sec: float
    coverage_pct: float

    source_count: int
    source_names: str

    laptop_sec: float
    desktop_sec: float
    iphone_sec: float
    habit_sec: float
    other_source_sec: float

    target_sec: float
    target_met: bool

    coverage_status: str
    overlap_status: str
    overall_status: str


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Analyze integrated multi-source Daily Time coverage, "
            "unaccounted time, overlap, patterns, and 80/20 concentration."
        )
    )

    parser.add_argument(
        "--date",
        help="Analyze one completed date in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--start-date",
        help="Inclusive analysis start date.",
    )

    parser.add_argument(
        "--end-date",
        help="Inclusive analysis end date.",
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=INTEGRATED_DIRECTORY,
        help=(
            "Directory containing "
            "Integrated_Daily_Time_YYYY-MM-DD.csv files."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="Directory for integration analysis outputs.",
    )

    parser.add_argument(
        "--unaccounted-target-hours",
        type=float,
        default=DEFAULT_UNACCOUNTED_TARGET_HOURS,
        help=(
            "Maximum target for Unaccounted Time in hours. "
            "Default: 3."
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


def resolve_requested_dates(
    args: argparse.Namespace,
) -> tuple[date | None, date | None]:
    """Resolve optional requested date boundaries."""
    if args.date:
        target = parse_date(args.date)
        return target, target

    if args.start_date or args.end_date:
        if not args.start_date or not args.end_date:
            raise ValueError(
                "--start-date and --end-date must be used together."
            )

        start = parse_date(args.start_date)
        end = parse_date(args.end_date)

        if end < start:
            raise ValueError(
                f"End date {end} cannot be before start date {start}."
            )

        return start, end

    return None, None


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


def discover_files(
    input_dir: Path,
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[date, Path]]:
    """Discover integrated daily datasets."""
    if not input_dir.exists():
        raise FileNotFoundError(
            f"Integrated input directory does not exist: "
            f"{input_dir}"
        )

    discovered: list[tuple[date, Path]] = []

    for path in sorted(
        input_dir.glob("Integrated_Daily_Time_*.csv")
    ):
        stem = path.stem
        prefix = "Integrated_Daily_Time_"

        if not stem.startswith(prefix):
            continue

        value = stem[len(prefix):]

        try:
            target_date = parse_date(value)
        except ValueError:
            continue

        if start_date and target_date < start_date:
            continue

        if end_date and target_date > end_date:
            continue

        discovered.append(
            (
                target_date,
                path,
            )
        )

    discovered.sort(
        key=lambda item: item[0]
    )

    return discovered


def read_csv(
    path: Path,
) -> list[dict[str, str]]:
    """Read a UTF-8 CSV dataset."""
    with path.open(
        mode="r",
        newline="",
        encoding=CSV_ENCODING,
    ) as file:
        return list(csv.DictReader(file))


def source_name_from_row(
    row: dict[str, str],
) -> str:
    """Return the most specific available source identifier."""
    source_name = (
        row.get("Source_Name")
        or ""
    ).strip()

    if source_name:
        return source_name

    source_device = (
        row.get("Source_Device")
        or ""
    ).strip()

    if source_device:
        return source_device

    source = (
        row.get("Source")
        or ""
    ).strip()

    return source or "unknown"


def source_type_from_row(
    row: dict[str, str],
) -> str:
    """Return the configured source type."""
    source_type = (
        row.get("Source_Type")
        or ""
    ).strip()

    if source_type:
        return source_type

    return (
        row.get("Source")
        or "unknown"
    ).strip()


def classify_source_bucket(
    source_name: str,
    source_type: str,
    source_device: str,
) -> str:
    """Map a configured source to an analysis bucket."""
    normalized = source_name.strip().lower()
    device = source_device.strip().lower()
    source_kind = source_type.strip().lower()

    if (
        normalized == "asus_laptop"
        or "asus" in normalized
        or "asus" in device
    ):
        return "laptop"

    if (
        normalized == "desktop"
        or "desktop" in normalized
        or "desktop" in device
    ):
        return "desktop"

    if (
        normalized == "iphone"
        or source_kind == "applescreentime"
        or "iphone" in device
    ):
        return "iphone"

    if (
        normalized == "habit"
        or source_kind == "habit"
    ):
        return "habit"

    return "other"


def calculate_source_metrics(
    rows: Iterable[dict[str, str]],
) -> tuple[
    dict[str, SourceMetric],
    float,
    dict[str, float],
]:
    """Calculate source and category duration totals."""
    source_totals: dict[
        str,
        float,
    ] = defaultdict(float)

    source_types: dict[
        str,
        str,
    ] = {}

    category_totals: dict[
        str,
        float,
    ] = defaultdict(float)

    for row in rows:
        duration = parse_float(
            row.get("Duration_sec"),
            "Duration_sec",
            Path("<integrated dataset>"),
        )

        if duration < 0:
            raise ValueError(
                "Duration_sec cannot be negative."
            )

        source_name = source_name_from_row(row)
        source_type = source_type_from_row(row)

        source_totals[source_name] += duration
        source_types[source_name] = source_type

        category = (
            row.get("Category")
            or "Uncategorized"
        ).strip()

        category_totals[category] += duration

    source_metrics = {
        name: SourceMetric(
            source_name=name,
            source_type=source_types[name],
            duration_sec=duration,
        )
        for name, duration in source_totals.items()
    }

    return (
        source_metrics,
        sum(source_totals.values()),
        dict(category_totals),
    )


def determine_coverage(
    recorded_sec: float,
    target_sec: float,
) -> tuple[
    float,
    float,
    float,
    bool,
    str,
    str,
]:
    """Calculate coverage, unaccounted time, and overlap."""
    if recorded_sec < 0:
        raise ValueError(
            "Recorded activity cannot be negative."
        )

    coverage_pct = min(
        recorded_sec / SECONDS_PER_DAY * 100,
        100.0,
    )

    unaccounted_sec = max(
        SECONDS_PER_DAY - recorded_sec,
        0.0,
    )

    overlap_excess_sec = max(
        recorded_sec - SECONDS_PER_DAY,
        0.0,
    )

    target_met = (
        overlap_excess_sec <= 0.001
        and unaccounted_sec <= target_sec
    )

    if overlap_excess_sec > 0.001:
        coverage_status = "OVERLAP"
    elif unaccounted_sec <= target_sec:
        coverage_status = "GOOD"
    elif unaccounted_sec <= 5 * 60 * 60:
        coverage_status = "REVIEW"
    else:
        coverage_status = "LOW_COVERAGE"

    if overlap_excess_sec > 0.001:
        overlap_status = "OVERLAP_REVIEW"
    else:
        overlap_status = "CLEAN"

    if overlap_excess_sec > 0.001:
        overall_status = "OVERLAP_REVIEW"
    elif unaccounted_sec <= target_sec:
        overall_status = "GOOD_COVERAGE"
    elif unaccounted_sec <= 5 * 60 * 60:
        overall_status = "REVIEW_COVERAGE"
    else:
        overall_status = "LOW_COVERAGE"

    return (
        coverage_pct,
        unaccounted_sec,
        overlap_excess_sec,
        target_met,
        coverage_status,
        overlap_status,
    )


def build_daily_analysis(
    target_date: date,
    rows: list[dict[str, str]],
    target_sec: float,
) -> DailyAnalysis:
    """Build daily integration analysis."""
    (
        source_metrics,
        recorded_sec,
        _,
    ) = calculate_source_metrics(rows)

    (
        coverage_pct,
        unaccounted_sec,
        overlap_excess_sec,
        target_met,
        coverage_status,
        overlap_status,
    ) = determine_coverage(
        recorded_sec,
        target_sec,
    )

    source_names = sorted(
        source_metrics
    )

    source_buckets = {
        "laptop": 0.0,
        "desktop": 0.0,
        "iphone": 0.0,
        "habit": 0.0,
        "other": 0.0,
    }

    for metric in source_metrics.values():
        bucket = classify_source_bucket(
            metric.source_name,
            metric.source_type,
            _source_device_for_metric(
                metric,
                rows,
            ),
        )

        source_buckets[bucket] += (
            metric.duration_sec
        )

    return DailyAnalysis(
        date=target_date,
        weekday=target_date.strftime("%A"),
        day_type=(
            "Weekend"
            if target_date.weekday() >= 5
            else "Weekday"
        ),
        recorded_sec=recorded_sec,
        unaccounted_sec=unaccounted_sec,
        overlap_excess_sec=overlap_excess_sec,
        coverage_pct=coverage_pct,
        source_count=len(source_names),
        source_names=", ".join(source_names),
        laptop_sec=source_buckets["laptop"],
        desktop_sec=source_buckets["desktop"],
        iphone_sec=source_buckets["iphone"],
        habit_sec=source_buckets["habit"],
        other_source_sec=source_buckets["other"],
        target_sec=target_sec,
        target_met=target_met,
        coverage_status=coverage_status,
        overlap_status=overlap_status,
        overall_status=(
            "OVERLAP_REVIEW"
            if overlap_excess_sec > 0.001
            else (
                "GOOD_COVERAGE"
                if target_met
                else (
                    "REVIEW_COVERAGE"
                    if unaccounted_sec
                    <= 5 * 60 * 60
                    else "LOW_COVERAGE"
                )
            )
        ),
    )


def _source_device_for_metric(
    metric: SourceMetric,
    rows: Iterable[dict[str, str]],
) -> str:
    """Find the source device associated with a source."""
    for row in rows:
        if (
            source_name_from_row(row)
            == metric.source_name
        ):
            return (
                row.get("Source_Device")
                or ""
            ).strip()

    return ""


def median_or_zero(
    values: Iterable[float],
) -> float:
    """Return median or zero for an empty sequence."""
    values_list = list(values)

    if not values_list:
        return 0.0

    return statistics.median(
        values_list
    )


def mean_or_zero(
    values: Iterable[float],
) -> float:
    """Return mean or zero for an empty sequence."""
    values_list = list(values)

    if not values_list:
        return 0.0

    return statistics.mean(
        values_list
    )


def percentile(
    values: Iterable[float],
    percentile_value: float,
) -> float:
    """Calculate a linear-interpolated percentile."""
    values_list = sorted(values)

    if not values_list:
        return 0.0

    if len(values_list) == 1:
        return values_list[0]

    position = (
        (len(values_list) - 1)
        * percentile_value
        / 100
    )

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values_list[lower]

    fraction = position - lower

    return (
        values_list[lower]
        + (
            values_list[upper]
            - values_list[lower]
        )
        * fraction
    )


def safe_percentage(
    numerator: float,
    denominator: float,
) -> float:
    """Calculate a percentage safely."""
    if denominator <= 0:
        return 0.0

    return (
        numerator
        / denominator
        * 100
    )


def calculate_aggregate_metrics(
    analyses: list[DailyAnalysis],
) -> dict[str, float]:
    """Calculate aggregate coverage metrics."""
    if not analyses:
        return {
            "days": 0,
            "good_days": 0,
            "review_days": 0,
            "low_coverage_days": 0,
            "overlap_days": 0,
            "target_met_pct": 0.0,
            "mean_recorded_sec": 0.0,
            "median_recorded_sec": 0.0,
            "mean_unaccounted_sec": 0.0,
            "median_unaccounted_sec": 0.0,
            "p25_unaccounted_sec": 0.0,
            "p75_unaccounted_sec": 0.0,
            "max_unaccounted_sec": 0.0,
            "mean_overlap_excess_sec": 0.0,
            "median_overlap_excess_sec": 0.0,
            "max_overlap_excess_sec": 0.0,
            "mean_coverage_pct": 0.0,
            "median_coverage_pct": 0.0,
        }

    recorded = [
        item.recorded_sec
        for item in analyses
    ]

    unaccounted = [
        item.unaccounted_sec
        for item in analyses
    ]

    overlap = [
        item.overlap_excess_sec
        for item in analyses
    ]

    coverage = [
        item.coverage_pct
        for item in analyses
    ]

    good_days = sum(
        item.overall_status
        == "GOOD_COVERAGE"
        for item in analyses
    )

    review_days = sum(
        item.overall_status
        == "REVIEW_COVERAGE"
        for item in analyses
    )

    low_days = sum(
        item.overall_status
        == "LOW_COVERAGE"
        for item in analyses
    )

    overlap_days = sum(
        item.overall_status
        == "OVERLAP_REVIEW"
        for item in analyses
    )

    return {
        "days": len(analyses),
        "good_days": good_days,
        "review_days": review_days,
        "low_coverage_days": low_days,
        "overlap_days": overlap_days,
        "target_met_pct": safe_percentage(
            good_days,
            len(analyses),
        ),
        "mean_recorded_sec": mean_or_zero(
            recorded
        ),
        "median_recorded_sec": median_or_zero(
            recorded
        ),
        "mean_unaccounted_sec": mean_or_zero(
            unaccounted
        ),
        "median_unaccounted_sec": median_or_zero(
            unaccounted
        ),
        "p25_unaccounted_sec": percentile(
            unaccounted,
            25,
        ),
        "p75_unaccounted_sec": percentile(
            unaccounted,
            75,
        ),
        "max_unaccounted_sec": max(
            unaccounted
        ),
        "mean_overlap_excess_sec": mean_or_zero(
            overlap
        ),
        "median_overlap_excess_sec": median_or_zero(
            overlap
        ),
        "max_overlap_excess_sec": max(
            overlap
        ),
        "mean_coverage_pct": mean_or_zero(
            coverage
        ),
        "median_coverage_pct": median_or_zero(
            coverage
        ),
    }


def calculate_source_aggregate(
    input_files: list[tuple[date, Path]],
) -> dict[str, float]:
    """Calculate source contribution across all selected dates."""
    totals: dict[str, float] = defaultdict(float)

    for _, path in input_files:
        rows = read_csv(path)

        for row in rows:
            source_name = source_name_from_row(row)

            duration = parse_float(
                row.get("Duration_sec"),
                "Duration_sec",
                path,
            )

            totals[source_name] += duration

    return dict(totals)


def calculate_category_aggregate(
    input_files: list[tuple[date, Path]],
) -> dict[str, float]:
    """Calculate category contribution across all selected dates."""
    totals: dict[str, float] = defaultdict(float)

    for _, path in input_files:
        rows = read_csv(path)

        for row in rows:
            category = (
                row.get("Category")
                or "Uncategorized"
            ).strip()

            duration = parse_float(
                row.get("Duration_sec"),
                "Duration_sec",
                path,
            )

            totals[category] += duration

    return dict(totals)


def calculate_80_20(
    totals: dict[str, float],
) -> list[dict[str, object]]:
    """Calculate cumulative concentration for an 80/20 analysis."""
    ordered = sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    total = sum(
        value
        for _, value in ordered
    )

    results: list[dict[str, object]] = []

    cumulative = 0.0

    for rank, (
        name,
        duration,
    ) in enumerate(
        ordered,
        start=1,
    ):
        cumulative += duration

        cumulative_pct = safe_percentage(
            cumulative,
            total,
        )

        results.append(
            {
                "Rank": rank,
                "Item": name,
                "Duration_sec": duration,
                "Duration_hours": duration / 3600,
                "Contribution_pct": safe_percentage(
                    duration,
                    total,
                ),
                "Cumulative_pct": cumulative_pct,
            }
        )

    return results


def calculate_weekday_weekend(
    analyses: list[DailyAnalysis],
) -> list[dict[str, object]]:
    """Calculate aggregate metrics by weekday/weekend."""
    groups: dict[
        str,
        list[DailyAnalysis],
    ] = defaultdict(list)

    for analysis in analyses:
        groups[
            analysis.day_type
        ].append(analysis)

    results: list[dict[str, object]] = []

    for group_name in (
        "Weekday",
        "Weekend",
    ):
        group = groups.get(
            group_name,
            [],
        )

        if not group:
            continue

        results.append(
            {
                "Day_Type": group_name,
                "Days": len(group),
                "Mean_Recorded_Hours": (
                    mean_or_zero(
                        item.recorded_sec
                        for item in group
                    )
                    / 3600
                ),
                "Median_Recorded_Hours": (
                    median_or_zero(
                        item.recorded_sec
                        for item in group
                    )
                    / 3600
                ),
                "Mean_Unaccounted_Hours": (
                    mean_or_zero(
                        item.unaccounted_sec
                        for item in group
                    )
                    / 3600
                ),
                "Median_Unaccounted_Hours": (
                    median_or_zero(
                        item.unaccounted_sec
                        for item in group
                    )
                    / 3600
                ),
                "Target_Met_Pct": safe_percentage(
                    sum(
                        item.target_met
                        for item in group
                    ),
                    len(group),
                ),
                "Overlap_Days": sum(
                    item.overlap_excess_sec
                    > 0.001
                    for item in group
                ),
            }
        )

    return results


def write_daily_analysis(
    analyses: list[DailyAnalysis],
    output_path: Path,
) -> None:
    """Write daily analysis CSV."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "Date",
        "Weekday",
        "Day_Type",
        "Recorded_Hours",
        "Unaccounted_Hours",
        "Overlap_Excess_Hours",
        "Coverage_Pct",
        "Source_Count",
        "Sources",
        "Laptop_Hours",
        "Desktop_Hours",
        "iPhone_Hours",
        "Habit_Hours",
        "Other_Source_Hours",
        "Unaccounted_Target_Hours",
        "Target_Met",
        "Coverage_Status",
        "Overlap_Status",
        "Overall_Status",
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

        for item in analyses:
            writer.writerow(
                {
                    "Date": item.date.isoformat(),
                    "Weekday": item.weekday,
                    "Day_Type": item.day_type,
                    "Recorded_Hours": round(
                        item.recorded_sec / 3600,
                        3,
                    ),
                    "Unaccounted_Hours": round(
                        item.unaccounted_sec / 3600,
                        3,
                    ),
                    "Overlap_Excess_Hours": round(
                        item.overlap_excess_sec / 3600,
                        3,
                    ),
                    "Coverage_Pct": round(
                        item.coverage_pct,
                        2,
                    ),
                    "Source_Count": item.source_count,
                    "Sources": item.source_names,
                    "Laptop_Hours": round(
                        item.laptop_sec / 3600,
                        3,
                    ),
                    "Desktop_Hours": round(
                        item.desktop_sec / 3600,
                        3,
                    ),
                    "iPhone_Hours": round(
                        item.iphone_sec / 3600,
                        3,
                    ),
                    "Habit_Hours": round(
                        item.habit_sec / 3600,
                        3,
                    ),
                    "Other_Source_Hours": round(
                        item.other_source_sec / 3600,
                        3,
                    ),
                    "Unaccounted_Target_Hours": round(
                        item.target_sec / 3600,
                        3,
                    ),
                    "Target_Met": item.target_met,
                    "Coverage_Status": item.coverage_status,
                    "Overlap_Status": item.overlap_status,
                    "Overall_Status": item.overall_status,
                }
            )


def write_key_value_csv(
    rows: list[dict[str, object]],
    fieldnames: list[str],
    output_path: Path,
) -> None:
    """Write a generic analysis CSV."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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
        writer.writerows(rows)


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

    return f"{hours}h {minutes:02d}m"


def format_pct(
    value: float,
) -> str:
    """Format percentage."""
    return f"{value:.1f}%"


def write_report(
    analyses: list[DailyAnalysis],
    aggregate: dict[str, float],
    source_totals: dict[str, float],
    category_totals: dict[str, float],
    weekday_weekend: list[dict[str, object]],
    target_hours: float,
    output_path: Path,
) -> None:
    """Write a human-readable analysis report."""
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_80_20 = calculate_80_20(
        source_totals
    )

    category_80_20 = calculate_80_20(
        category_totals
    )

    target_sec = target_hours * 3600

    good_days = int(
        aggregate["good_days"]
    )

    total_days = int(
        aggregate["days"]
    )

    with output_path.open(
        mode="w",
        encoding="utf-8",
    ) as file:
        file.write(
            "# Integrated Activity Coverage Analysis\n\n"
        )

        if analyses:
            file.write(
                f"Date range : "
                f"{analyses[0].date} → "
                f"{analyses[-1].date}\n"
            )

        file.write(
            f"Days       : {total_days}\n"
        )

        file.write(
            f"Unaccounted target : "
            f"{target_hours:.1f} hours\n\n"
        )

        file.write(
            "## Executive Summary\n\n"
        )

        file.write(
            f"- Mean recorded activity: "
            f"{format_duration(aggregate['mean_recorded_sec'])}\n"
        )

        file.write(
            f"- Median recorded activity: "
            f"{format_duration(aggregate['median_recorded_sec'])}\n"
        )

        file.write(
            f"- Mean unaccounted time: "
            f"{format_duration(aggregate['mean_unaccounted_sec'])}\n"
        )

        file.write(
            f"- Median unaccounted time: "
            f"{format_duration(aggregate['median_unaccounted_sec'])}\n"
        )

        file.write(
            f"- Days meeting <= {target_hours:.1f}h target: "
            f"{good_days}/{total_days} "
            f"({format_pct(aggregate['target_met_pct'])})\n"
        )

        file.write(
            f"- Overlap-review days: "
            f"{int(aggregate['overlap_days'])}\n"
        )

        file.write(
            f"- Mean coverage: "
            f"{format_pct(aggregate['mean_coverage_pct'])}\n"
        )

        file.write(
            f"- Median coverage: "
            f"{format_pct(aggregate['median_coverage_pct'])}\n\n"
        )

        file.write(
            "## Interpretation\n\n"
        )

        file.write(
            "Unaccounted Time is an analytical balance, not a "
            "claim that the time is unknown. It may include meals, "
            "personal care, commuting, chores, active breaks, "
            "unregistered habits, and other off-device activity.\n\n"
        )

        file.write(
            "Recorded Activity is the sum of integrated source "
            "durations. Because multiple trackers can overlap, "
            "Recorded Activity above 24 hours is treated as an "
            "overlap signal rather than literal time spent.\n\n"
        )

        file.write(
            "The objective is practical 80/20 coverage: enough "
            "reliable information to identify dominant patterns, "
            "bottlenecks, behaviors, and process improvements "
            "without requiring minute-perfect classification.\n\n"
        )

        file.write(
            "## Source Contribution\n\n"
        )

        total_source_seconds = sum(
            source_totals.values()
        )

        for item in source_80_20:
            file.write(
                f"- {item['Item']}: "
                f"{format_duration(item['Duration_sec'])} "
                f"({format_pct(item['Contribution_pct'])})\n"
            )

        file.write(
            f"\nTotal source-recorded duration: "
            f"{format_duration(total_source_seconds)}\n\n"
        )

        file.write(
            "## 80/20 Source Concentration\n\n"
        )

        source_80_count = 0

        for item in source_80_20:
            source_80_count += 1

            if item["Cumulative_pct"] >= 80:
                break

        file.write(
            f"The top {source_80_count} source(s) account for "
            f"at least 80% of recorded source duration.\n\n"
        )

        file.write(
            "## 80/20 Category Concentration\n\n"
        )

        category_80_count = 0

        for item in category_80_20:
            category_80_count += 1

            if item["Cumulative_pct"] >= 80:
                break

        file.write(
            f"The top {category_80_count} category/categories "
            "account for at least 80% of recorded category duration.\n\n"
        )

        for item in category_80_20[
            : min(10, len(category_80_20))
        ]:
            file.write(
                f"- {item['Item']}: "
                f"{format_duration(item['Duration_sec'])} "
                f"({format_pct(item['Contribution_pct'])}, "
                f"cumulative "
                f"{format_pct(item['Cumulative_pct'])})\n"
            )

        file.write(
            "\n## Weekday / Weekend\n\n"
        )

        for item in weekday_weekend:
            file.write(
                f"{item['Day_Type']}:\n"
            )

            file.write(
                f"  Days: {item['Days']}\n"
            )

            file.write(
                f"  Mean recorded: "
                f"{item['Mean_Recorded_Hours']:.2f}h\n"
            )

            file.write(
                f"  Median recorded: "
                f"{item['Median_Recorded_Hours']:.2f}h\n"
            )

            file.write(
                f"  Mean unaccounted: "
                f"{item['Mean_Unaccounted_Hours']:.2f}h\n"
            )

            file.write(
                f"  Median unaccounted: "
                f"{item['Median_Unaccounted_Hours']:.2f}h\n"
            )

            file.write(
                f"  Target met: "
                f"{item['Target_Met_Pct']:.1f}%\n"
            )

            file.write(
                f"  Overlap days: "
                f"{item['Overlap_Days']}\n\n"
            )

        file.write(
            "## Daily Status\n\n"
        )

        for item in analyses:
            file.write(
                f"{item.date} "
                f"{item.overall_status}: "
                f"recorded "
                f"{format_duration(item.recorded_sec)}, "
                f"unaccounted "
                f"{format_duration(item.unaccounted_sec)}, "
                f"overlap excess "
                f"{format_duration(item.overlap_excess_sec)}\n"
            )

        file.write(
            "\n## Interpretation Thresholds\n\n"
        )

        file.write(
            f"- GOOD_COVERAGE: unaccounted <= "
            f"{target_hours:.1f}h\n"
        )

        file.write(
            "- REVIEW_COVERAGE: unaccounted > target "
            "and <= 5h\n"
        )

        file.write(
            "- LOW_COVERAGE: unaccounted > 5h\n"
        )

        file.write(
            "- OVERLAP_REVIEW: recorded activity > 24h\n"
        )

        file.write(
            "\nThese are diagnostic thresholds, not accounting rules.\n"
        )


def write_summary_csv(
    aggregate: dict[str, float],
    target_hours: float,
    output_path: Path,
) -> None:
    """Write aggregate summary CSV."""
    rows = [
        {
            "Metric": "Days",
            "Value": aggregate["days"],
        },
        {
            "Metric": "Good_Days",
            "Value": aggregate["good_days"],
        },
        {
            "Metric": "Review_Days",
            "Value": aggregate["review_days"],
        },
        {
            "Metric": "Low_Coverage_Days",
            "Value": aggregate["low_coverage_days"],
        },
        {
            "Metric": "Overlap_Days",
            "Value": aggregate["overlap_days"],
        },
        {
            "Metric": "Target_Hours",
            "Value": target_hours,
        },
        {
            "Metric": "Target_Met_Pct",
            "Value": round(
                aggregate["target_met_pct"],
                2,
            ),
        },
        {
            "Metric": "Mean_Recorded_Hours",
            "Value": round(
                aggregate["mean_recorded_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Median_Recorded_Hours",
            "Value": round(
                aggregate["median_recorded_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Mean_Unaccounted_Hours",
            "Value": round(
                aggregate["mean_unaccounted_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Median_Unaccounted_Hours",
            "Value": round(
                aggregate["median_unaccounted_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "P25_Unaccounted_Hours",
            "Value": round(
                aggregate["p25_unaccounted_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "P75_Unaccounted_Hours",
            "Value": round(
                aggregate["p75_unaccounted_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Max_Unaccounted_Hours",
            "Value": round(
                aggregate["max_unaccounted_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Mean_Overlap_Excess_Hours",
            "Value": round(
                aggregate["mean_overlap_excess_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Median_Overlap_Excess_Hours",
            "Value": round(
                aggregate["median_overlap_excess_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Max_Overlap_Excess_Hours",
            "Value": round(
                aggregate["max_overlap_excess_sec"] / 3600,
                3,
            ),
        },
        {
            "Metric": "Mean_Coverage_Pct",
            "Value": round(
                aggregate["mean_coverage_pct"],
                2,
            ),
        },
        {
            "Metric": "Median_Coverage_Pct",
            "Value": round(
                aggregate["median_coverage_pct"],
                2,
            ),
        },
    ]

    write_key_value_csv(
        rows,
        [
            "Metric",
            "Value",
        ],
        output_path,
    )


def write_concentration_csv(
    totals: dict[str, float],
    output_path: Path,
) -> None:
    """Write 80/20 concentration data."""
    rows = calculate_80_20(
        totals
    )

    write_key_value_csv(
        rows,
        [
            "Rank",
            "Item",
            "Duration_sec",
            "Duration_hours",
            "Contribution_pct",
            "Cumulative_pct",
        ],
        output_path,
    )


def main() -> int:
    """Run the integration analysis."""
    args = parse_arguments()

    try:
        if args.unaccounted_target_hours < 0:
            raise ValueError(
                "--unaccounted-target-hours cannot be negative."
            )

        start_date, end_date = (
            resolve_requested_dates(args)
        )

        input_files = discover_files(
            args.input_dir,
            start_date,
            end_date,
        )

        if not input_files:
            raise FileNotFoundError(
                "No integrated daily datasets found in "
                f"{args.input_dir}."
            )

        target_sec = (
            args.unaccounted_target_hours
            * 3600
        )

        print(
            "# Integration Analysis"
        )
        print()
        print(
            f"Input       : {args.input_dir}"
        )
        print(
            f"Dates       : "
            f"{input_files[0][0]} → "
            f"{input_files[-1][0]}"
        )
        print(
            f"Days        : {len(input_files)}"
        )
        print(
            f"Unaccounted target : "
            f"{args.unaccounted_target_hours:.1f}h"
        )
        print(
            f"Output      : {args.output_dir}"
        )

        analyses: list[DailyAnalysis] = []

        for target_date, path in input_files:
            rows = read_csv(path)

            analysis = build_daily_analysis(
                target_date,
                rows,
                target_sec,
            )

            analyses.append(
                analysis
            )

            print()
            print(
                f"--- {target_date} ---"
            )
            print(
                f"Recorded Activity : "
                f"{format_duration(analysis.recorded_sec)}"
            )
            print(
                f"Unaccounted Time  : "
                f"{format_duration(analysis.unaccounted_sec)}"
            )
            print(
                f"Coverage          : "
                f"{analysis.coverage_pct:.1f}%"
            )
            print(
                f"Overlap Excess    : "
                f"{format_duration(analysis.overlap_excess_sec)}"
            )
            print(
                f"Status            : "
                f"{analysis.overall_status}"
            )

        aggregate = calculate_aggregate_metrics(
            analyses
        )

        source_totals = calculate_source_aggregate(
            input_files
        )

        category_totals = calculate_category_aggregate(
            input_files
        )

        weekday_weekend = (
            calculate_weekday_weekend(
                analyses
            )
        )

        args.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        daily_output = (
            args.output_dir
            / "Daily_Integration_Analysis.csv"
        )

        summary_output = (
            args.output_dir
            / "Integration_Analysis_Summary.csv"
        )

        source_output = (
            args.output_dir
            / "Integration_Source_80_20.csv"
        )

        category_output = (
            args.output_dir
            / "Integration_Category_80_20.csv"
        )

        report_output = (
            args.output_dir
            / "Integration_Analysis_Report.txt"
        )

        weekday_output = (
            args.output_dir
            / "Integration_Weekday_Weekend.csv"
        )

        write_daily_analysis(
            analyses,
            daily_output,
        )

        write_summary_csv(
            aggregate,
            args.unaccounted_target_hours,
            summary_output,
        )

        write_concentration_csv(
            source_totals,
            source_output,
        )

        write_concentration_csv(
            category_totals,
            category_output,
        )

        write_key_value_csv(
            weekday_weekend,
            [
                "Day_Type",
                "Days",
                "Mean_Recorded_Hours",
                "Median_Recorded_Hours",
                "Mean_Unaccounted_Hours",
                "Median_Unaccounted_Hours",
                "Target_Met_Pct",
                "Overlap_Days",
            ],
            weekday_output,
        )

        write_report(
            analyses,
            aggregate,
            source_totals,
            category_totals,
            weekday_weekend,
            args.unaccounted_target_hours,
            report_output,
        )

        print()
        print(
            "=" * 68
        )
        print(
            "=== Integration Analysis Summary ==="
        )
        print(
            "=" * 68
        )
        print(
            f"Days analyzed       : "
            f"{aggregate['days']}"
        )
        print(
            f"Mean recorded      : "
            f"{format_duration(aggregate['mean_recorded_sec'])}"
        )
        print(
            f"Median recorded    : "
            f"{format_duration(aggregate['median_recorded_sec'])}"
        )
        print(
            f"Mean unaccounted   : "
            f"{format_duration(aggregate['mean_unaccounted_sec'])}"
        )
        print(
            f"Median unaccounted : "
            f"{format_duration(aggregate['median_unaccounted_sec'])}"
        )
        print(
            f"Target <= "
            f"{args.unaccounted_target_hours:.1f}h "
            f"met on            : "
            f"{aggregate['good_days']}/"
            f"{aggregate['days']} days "
            f"({aggregate['target_met_pct']:.1f}%)"
        )
        print(
            f"Coverage review    : "
            f"{aggregate['review_days']} days"
        )
        print(
            f"Low coverage       : "
            f"{aggregate['low_coverage_days']} days"
        )
        print(
            f"Overlap review     : "
            f"{aggregate['overlap_days']} days"
        )
        print(
            f"Mean coverage      : "
            f"{aggregate['mean_coverage_pct']:.1f}%"
        )
        print(
            f"Median coverage    : "
            f"{aggregate['median_coverage_pct']:.1f}%"
        )

        print()
        print(
            "Outputs:"
        )
        print(
            f"  {daily_output}"
        )
        print(
            f"  {summary_output}"
        )
        print(
            f"  {source_output}"
        )
        print(
            f"  {category_output}"
        )
        print(
            f"  {weekday_output}"
        )
        print(
            f"  {report_output}"
        )

        print()
        print(
            "RESULT: INTEGRATION ANALYSIS PASSED."
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