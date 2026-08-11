"""
time_analysis.py

Read-only analysis layer for the ActivityWatch -> Fact_Time -> Daily_Time
pipeline.

Input:
    output/Daily_Time/Daily_Time.csv

Output:
    output/Analysis/Time/
        Time_Analysis_<start>_<end>.csv
        Time_Analysis_<start>_<end>.txt

The script never modifies the Daily_Time source dataset.

Examples:
    python time_analysis.py
    python time_analysis.py --date 2026-08-10
    python time_analysis.py --start-date 2026-08-01 --end-date 2026-08-10
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


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "output"

DAILY_TIME_PATH = (
    OUTPUT_ROOT
    / "Daily_Time"
    / "Daily_Time.csv"
)

ANALYSIS_ROOT = (
    OUTPUT_ROOT
    / "Analysis"
    / "Time"
)

REQUIRED_COLUMNS = {
    "Date",
    "Category",
    "Subcategory",
    "Duration_sec",
    "Duration_min",
    "Duration_hours",
    "Event_Count",
}


@dataclass(frozen=True)
class DailyRecord:
    """One Date × Category × Subcategory record."""

    date: date
    category: str
    subcategory: str
    duration_sec: float
    event_count: int


@dataclass(frozen=True)
class CategorySummary:
    """Aggregated category statistics."""

    category: str
    duration_sec: float
    percentage: float
    event_count: int
    active_days: int


@dataclass(frozen=True)
class SubcategorySummary:
    """Aggregated subcategory statistics."""

    category: str
    subcategory: str
    duration_sec: float
    percentage: float
    event_count: int
    active_days: int


@dataclass(frozen=True)
class DailySummary:
    """Aggregated daily statistics."""

    date: date
    duration_sec: float
    event_count: int
    category_count: int


@dataclass(frozen=True)
class AnalysisResult:
    """Complete analysis result."""

    start_date: date
    end_date: date
    calendar_days: int
    active_days: int
    zero_activity_days: int
    total_duration_sec: float
    total_event_count: int
    category_summaries: list[CategorySummary]
    subcategory_summaries: list[SubcategorySummary]
    daily_summaries: list[DailySummary]
    zero_activity_dates: list[date]


class AnalysisError(Exception):
    """Raised when analysis cannot be completed safely."""


def parse_date(value: str) -> date:
    """Parse an ISO date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def today_local() -> date:
    """Return the local calendar date."""
    return datetime.now().astimezone().date()


def validate_completed_date(
    target_date: date,
    include_today: bool,
) -> None:
    """Prevent accidental analysis of an incomplete current day."""
    if target_date == today_local() and not include_today:
        raise AnalysisError(
            f"{target_date.isoformat()} is the current day and is "
            "excluded by default. Use --include-today if explicitly "
            "needed."
        )


def resolve_date_range(
    args: argparse.Namespace,
) -> tuple[date, date]:
    """Resolve CLI arguments into an inclusive date range."""
    if args.date and (
        args.start_date is not None
        or args.end_date is not None
    ):
        raise AnalysisError(
            "--date cannot be combined with --start-date or --end-date."
        )

    if args.date:
        start_date = args.date
        end_date = args.date

    elif args.start_date or args.end_date:
        if args.start_date is None or args.end_date is None:
            raise AnalysisError(
                "--start-date and --end-date must be supplied together."
            )

        start_date = args.start_date
        end_date = args.end_date

    else:
        end_date = today_local() - timedelta(days=1)
        start_date = end_date

    if start_date > end_date:
        raise AnalysisError(
            "Start date cannot be later than end date."
        )

    if not args.include_today:
        if end_date >= today_local():
            end_date = today_local() - timedelta(days=1)

        if start_date > end_date:
            raise AnalysisError(
                "The requested range contains no completed days."
            )

    return start_date, end_date


def validate_input_file(path: Path) -> None:
    """Ensure the Daily_Time dataset exists."""
    if not path.exists():
        raise AnalysisError(
            f"Daily_Time dataset not found: {path}"
        )

    if not path.is_file():
        raise AnalysisError(
            f"Daily_Time path is not a file: {path}"
        )


def parse_float(
    value: str,
    column: str,
    row_number: int,
) -> float:
    """Parse a numeric CSV value."""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisError(
            f"Row {row_number}: invalid {column}: {value!r}"
        ) from exc

    if result < 0:
        raise AnalysisError(
            f"Row {row_number}: {column} cannot be negative."
        )

    return result


def parse_int(
    value: str,
    column: str,
    row_number: int,
) -> int:
    """Parse a non-negative integer CSV value."""
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisError(
            f"Row {row_number}: invalid {column}: {value!r}"
        ) from exc

    if result < 0:
        raise AnalysisError(
            f"Row {row_number}: {column} cannot be negative."
        )

    return result


def normalize_subcategory(value: str | None) -> str:
    """Represent missing subcategories consistently."""
    value = (value or "").strip()
    return value if value else "(none)"


def read_daily_time(
    path: Path,
    start_date: date,
    end_date: date,
) -> list[DailyRecord]:
    """Read and validate Daily_Time records in the requested range."""
    validate_input_file(path)

    records: list[DailyRecord] = []
    seen_keys: set[tuple[date, str, str]] = set()

    with path.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise AnalysisError(
                f"Daily_Time CSV has no header: {path}"
            )

        actual_columns = set(reader.fieldnames)
        missing_columns = sorted(
            REQUIRED_COLUMNS - actual_columns
        )

        if missing_columns:
            raise AnalysisError(
                "Daily_Time CSV is missing required columns: "
                f"{missing_columns}"
            )

        for row_number, row in enumerate(reader, start=2):
            raw_date = (row.get("Date") or "").strip()

            try:
                record_date = datetime.strptime(
                    raw_date,
                    "%Y-%m-%d",
                ).date()
            except ValueError as exc:
                raise AnalysisError(
                    f"Row {row_number}: invalid Date: {raw_date!r}"
                ) from exc

            if not start_date <= record_date <= end_date:
                continue

            category = (row.get("Category") or "").strip()

            if not category:
                raise AnalysisError(
                    f"Row {row_number}: Category is empty."
                )

            subcategory = normalize_subcategory(
                row.get("Subcategory")
            )

            duration_sec = parse_float(
                row.get("Duration_sec", ""),
                "Duration_sec",
                row_number,
            )

            event_count = parse_int(
                row.get("Event_Count", ""),
                "Event_Count",
                row_number,
            )

            key = (
                record_date,
                category,
                subcategory,
            )

            if key in seen_keys:
                raise AnalysisError(
                    "Duplicate Daily_Time key detected at "
                    f"row {row_number}: "
                    f"{record_date}, {category}, {subcategory}"
                )

            seen_keys.add(key)

            records.append(
                DailyRecord(
                    date=record_date,
                    category=category,
                    subcategory=subcategory,
                    duration_sec=duration_sec,
                    event_count=event_count,
                )
            )

    return records


def daterange(
    start_date: date,
    end_date: date,
) -> Iterable[date]:
    """Yield every date in an inclusive range."""
    current = start_date

    while current <= end_date:
        yield current
        current += timedelta(days=1)


def calculate_daily_summaries(
    records: list[DailyRecord],
    start_date: date,
    end_date: date,
) -> tuple[list[DailySummary], list[date]]:
    """Calculate daily totals and identify zero-activity days."""
    duration_by_date: defaultdict[date, float] = defaultdict(float)
    events_by_date: defaultdict[date, int] = defaultdict(int)
    categories_by_date: defaultdict[date, set[str]] = defaultdict(set)

    for record in records:
        duration_by_date[record.date] += record.duration_sec
        events_by_date[record.date] += record.event_count
        categories_by_date[record.date].add(record.category)

    summaries: list[DailySummary] = []
    zero_activity_dates: list[date] = []

    for current_date in daterange(start_date, end_date):
        duration_sec = duration_by_date[current_date]
        event_count = events_by_date[current_date]
        category_count = len(categories_by_date[current_date])

        if duration_sec <= 0:
            zero_activity_dates.append(current_date)

        summaries.append(
            DailySummary(
                date=current_date,
                duration_sec=duration_sec,
                event_count=event_count,
                category_count=category_count,
            )
        )

    return summaries, zero_activity_dates


def calculate_category_summaries(
    records: list[DailyRecord],
    total_duration_sec: float,
) -> list[CategorySummary]:
    """Aggregate records by category."""
    duration_by_category: defaultdict[str, float] = defaultdict(float)
    events_by_category: defaultdict[str, int] = defaultdict(int)
    dates_by_category: defaultdict[str, set[date]] = defaultdict(set)

    for record in records:
        duration_by_category[record.category] += record.duration_sec
        events_by_category[record.category] += record.event_count
        dates_by_category[record.category].add(record.date)

    summaries = []

    for category, duration_sec in duration_by_category.items():
        percentage = (
            duration_sec / total_duration_sec * 100
            if total_duration_sec
            else 0.0
        )

        summaries.append(
            CategorySummary(
                category=category,
                duration_sec=duration_sec,
                percentage=percentage,
                event_count=events_by_category[category],
                active_days=len(dates_by_category[category]),
            )
        )

    return sorted(
        summaries,
        key=lambda item: item.duration_sec,
        reverse=True,
    )


def calculate_subcategory_summaries(
    records: list[DailyRecord],
    total_duration_sec: float,
) -> list[SubcategorySummary]:
    """Aggregate records by category and subcategory."""
    durations: defaultdict[tuple[str, str], float] = defaultdict(float)
    events: defaultdict[tuple[str, str], int] = defaultdict(int)
    dates: defaultdict[tuple[str, str], set[date]] = defaultdict(set)

    for record in records:
        key = (
            record.category,
            record.subcategory,
        )

        durations[key] += record.duration_sec
        events[key] += record.event_count
        dates[key].add(record.date)

    summaries = []

    for (
        category,
        subcategory,
    ), duration_sec in durations.items():
        percentage = (
            duration_sec / total_duration_sec * 100
            if total_duration_sec
            else 0.0
        )

        summaries.append(
            SubcategorySummary(
                category=category,
                subcategory=subcategory,
                duration_sec=duration_sec,
                percentage=percentage,
                event_count=events[(category, subcategory)],
                active_days=len(
                    dates[(category, subcategory)]
                ),
            )
        )

    return sorted(
        summaries,
        key=lambda item: item.duration_sec,
        reverse=True,
    )


def validate_analysis_totals(
    records: list[DailyRecord],
    daily_summaries: list[DailySummary],
    category_summaries: list[CategorySummary],
    subcategory_summaries: list[SubcategorySummary],
) -> None:
    """Verify that aggregation layers reconcile."""
    source_duration = sum(
        record.duration_sec
        for record in records
    )

    daily_duration = sum(
        summary.duration_sec
        for summary in daily_summaries
    )

    category_duration = sum(
        summary.duration_sec
        for summary in category_summaries
    )

    subcategory_duration = sum(
        summary.duration_sec
        for summary in subcategory_summaries
    )

    tolerance = 0.001

    checks = {
        "daily": daily_duration,
        "category": category_duration,
        "subcategory": subcategory_duration,
    }

    for name, value in checks.items():
        if abs(source_duration - value) > tolerance:
            raise AnalysisError(
                f"Duration reconciliation failed for {name}: "
                f"source={source_duration:.3f}, "
                f"aggregated={value:.3f}"
            )


def analyze(
    records: list[DailyRecord],
    start_date: date,
    end_date: date,
) -> AnalysisResult:
    """Build the complete analysis result."""
    total_duration_sec = sum(
        record.duration_sec
        for record in records
    )

    total_event_count = sum(
        record.event_count
        for record in records
    )

    daily_summaries, zero_activity_dates = (
        calculate_daily_summaries(
            records,
            start_date,
            end_date,
        )
    )

    category_summaries = calculate_category_summaries(
        records,
        total_duration_sec,
    )

    subcategory_summaries = (
        calculate_subcategory_summaries(
            records,
            total_duration_sec,
        )
    )

    validate_analysis_totals(
        records,
        daily_summaries,
        category_summaries,
        subcategory_summaries,
    )

    active_days = (
        len(daily_summaries)
        - len(zero_activity_dates)
    )

    return AnalysisResult(
        start_date=start_date,
        end_date=end_date,
        calendar_days=len(daily_summaries),
        active_days=active_days,
        zero_activity_days=len(zero_activity_dates),
        total_duration_sec=total_duration_sec,
        total_event_count=total_event_count,
        category_summaries=category_summaries,
        subcategory_summaries=subcategory_summaries,
        daily_summaries=daily_summaries,
        zero_activity_dates=zero_activity_dates,
    )


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    total_minutes = round(seconds / 60)

    hours, minutes = divmod(
        total_minutes,
        60,
    )

    if hours and minutes:
        return f"{hours}h {minutes}m"

    if hours:
        return f"{hours}h"

    return f"{minutes}m"


def format_percentage(value: float) -> str:
    """Format a percentage."""
    return f"{value:.1f}%"


def write_analysis_csv(
    result: AnalysisResult,
    path: Path,
) -> None:
    """Write a machine-readable analysis dataset."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            [
                "Section",
                "Date",
                "Category",
                "Subcategory",
                "Duration_sec",
                "Duration_min",
                "Duration_hours",
                "Percentage",
                "Event_Count",
                "Active_Days",
                "Calendar_Days",
            ]
        )

        for summary in result.daily_summaries:
            writer.writerow(
                [
                    "Daily",
                    summary.date.isoformat(),
                    "",
                    "",
                    f"{summary.duration_sec:.3f}",
                    f"{summary.duration_sec / 60:.3f}",
                    f"{summary.duration_sec / 3600:.4f}",
                    "",
                    summary.event_count,
                    int(summary.duration_sec > 0),
                    1,
                ]
            )

        for summary in result.category_summaries:
            writer.writerow(
                [
                    "Category",
                    "",
                    summary.category,
                    "",
                    f"{summary.duration_sec:.3f}",
                    f"{summary.duration_sec / 60:.3f}",
                    f"{summary.duration_sec / 3600:.4f}",
                    f"{summary.percentage:.4f}",
                    summary.event_count,
                    summary.active_days,
                    result.calendar_days,
                ]
            )

        for summary in result.subcategory_summaries:
            writer.writerow(
                [
                    "Subcategory",
                    "",
                    summary.category,
                    summary.subcategory,
                    f"{summary.duration_sec:.3f}",
                    f"{summary.duration_sec / 60:.3f}",
                    f"{summary.duration_sec / 3600:.4f}",
                    f"{summary.percentage:.4f}",
                    summary.event_count,
                    summary.active_days,
                    result.calendar_days,
                ]
            )


def write_text_report(
    result: AnalysisResult,
    path: Path,
) -> None:
    """Write a human-readable analysis report."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    total_duration = result.total_duration_sec

    average_calendar = (
        total_duration / result.calendar_days
        if result.calendar_days
        else 0.0
    )

    average_active = (
        total_duration / result.active_days
        if result.active_days
        else 0.0
    )

    lines: list[str] = []

    lines.append("Activity Time Analysis")
    lines.append("=" * 60)
    lines.append("")
    lines.append(
        f"Date range        : "
        f"{result.start_date.isoformat()} → "
        f"{result.end_date.isoformat()}"
    )
    lines.append("Mode              : COMPLETED DAYS ONLY")
    lines.append(
        f"Calendar days     : {result.calendar_days}"
    )
    lines.append(
        f"Active days       : {result.active_days}"
    )
    lines.append(
        f"Zero-activity days: {result.zero_activity_days}"
    )
    lines.append(
        f"Total tracked time: "
        f"{format_duration(total_duration)}"
    )
    lines.append(
        f"Average/calendar  : "
        f"{format_duration(average_calendar)}"
    )
    lines.append(
        f"Average/active    : "
        f"{format_duration(average_active)}"
    )
    lines.append(
        f"Event count       : "
        f"{result.total_event_count:,}"
    )
    lines.append("")

    lines.append("Category Breakdown")
    lines.append("-" * 60)

    for summary in result.category_summaries:
        lines.append(
            f"{format_duration(summary.duration_sec):>8} "
            f"{format_percentage(summary.percentage):>7} "
            f"{summary.category}"
        )

    lines.append("")
    lines.append("Top Subcategories")
    lines.append("-" * 60)

    for summary in result.subcategory_summaries[:20]:
        label = (
            f"{summary.category} > "
            f"{summary.subcategory}"
        )

        lines.append(
            f"{format_duration(summary.duration_sec):>8} "
            f"{format_percentage(summary.percentage):>7} "
            f"{label}"
        )

    lines.append("")
    lines.append("Daily Breakdown")
    lines.append("-" * 60)

    for summary in result.daily_summaries:
        lines.append(
            f"{summary.date.isoformat()}  "
            f"{format_duration(summary.duration_sec):>8}  "
            f"{summary.event_count:>6,} events  "
            f"{summary.category_count:>2} categories"
        )

    lines.append("")

    if result.zero_activity_dates:
        lines.append("Zero-Activity Dates")
        lines.append("-" * 60)

        for current_date in result.zero_activity_dates:
            lines.append(
                current_date.isoformat()
            )

        lines.append("")

    lines.append("Data Integrity")
    lines.append("-" * 60)
    lines.append(
        "PASS  Daily totals reconcile with source records."
    )
    lines.append(
        "PASS  Category totals reconcile with source records."
    )
    lines.append(
        "PASS  Subcategory totals reconcile with source records."
    )
    lines.append(
        "PASS  No negative durations detected."
    )
    lines.append(
        "PASS  No duplicate analysis keys detected."
    )

    lines.append("")
    lines.append(
        "RESULT: TIME ANALYSIS COMPLETED SUCCESSFULLY."
    )

    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def print_console_report(
    result: AnalysisResult,
    csv_path: Path,
    text_path: Path,
) -> None:
    """Print the analysis summary."""
    total_duration = result.total_duration_sec

    average_calendar = (
        total_duration / result.calendar_days
        if result.calendar_days
        else 0.0
    )

    average_active = (
        total_duration / result.active_days
        if result.active_days
        else 0.0
    )

    print()
    print("# Time Analysis")
    print()
    print(
        f"Dates : "
        f"{result.start_date.isoformat()} → "
        f"{result.end_date.isoformat()}"
    )
    print("Mode  : COMPLETED DAYS ONLY")
    print()

    print("=== Period Summary ===")
    print(
        f"Calendar days      : "
        f"{result.calendar_days}"
    )
    print(
        f"Active days        : "
        f"{result.active_days}"
    )
    print(
        f"Zero-activity days : "
        f"{result.zero_activity_days}"
    )
    print(
        f"Total tracked time : "
        f"{format_duration(total_duration)}"
    )
    print(
        f"Average / calendar : "
        f"{format_duration(average_calendar)}"
    )
    print(
        f"Average / active   : "
        f"{format_duration(average_active)}"
    )
    print(
        f"Events             : "
        f"{result.total_event_count:,}"
    )
    print()

    print("=== Category Breakdown ===")

    for summary in result.category_summaries:
        print(
            f"{format_duration(summary.duration_sec):>8} "
            f"{format_percentage(summary.percentage):>7}  "
            f"{summary.category}"
        )

    print()
    print("=== Top 15 Subcategories ===")

    for summary in result.subcategory_summaries[:15]:
        print(
            f"{format_duration(summary.duration_sec):>8} "
            f"{format_percentage(summary.percentage):>7}  "
            f"{summary.category} > "
            f"{summary.subcategory}"
        )

    print()
    print("=== Daily Breakdown ===")

    for summary in result.daily_summaries:
        print(
            f"{summary.date.isoformat()}  "
            f"{format_duration(summary.duration_sec):>8}  "
            f"{summary.category_count:>2} categories  "
            f"{summary.event_count:>6,} events"
        )

    if result.zero_activity_dates:
        print()
        print("=== Zero-Activity Dates ===")

        for current_date in result.zero_activity_dates:
            print(
                f"- {current_date.isoformat()}"
            )

    print()
    print("=== Data Integrity ===")
    print(
        "PASS  Daily totals reconcile."
    )
    print(
        "PASS  Category totals reconcile."
    )
    print(
        "PASS  Subcategory totals reconcile."
    )
    print(
        "PASS  No negative durations."
    )
    print(
        "PASS  No duplicate analysis keys."
    )

    print()
    print("=== Output ===")
    print(f"CSV : {csv_path}")
    print(f"TXT : {text_path}")

    print()
    print(
        "RESULT: TIME ANALYSIS COMPLETED SUCCESSFULLY."
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Analyze the Daily_Time dataset."
        )
    )

    parser.add_argument(
        "--date",
        type=parse_date,
        help="Analyze one completed date.",
    )

    parser.add_argument(
        "--start-date",
        type=parse_date,
        help="Inclusive analysis start date.",
    )

    parser.add_argument(
        "--end-date",
        type=parse_date,
        help="Inclusive analysis end date.",
    )

    parser.add_argument(
        "--include-today",
        action="store_true",
        help=(
            "Allow analysis of the current incomplete day."
        ),
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DAILY_TIME_PATH,
        help=(
            "Path to Daily_Time.csv."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ANALYSIS_ROOT,
        help=(
            "Directory for analysis outputs."
        ),
    )

    return parser


def main() -> int:
    """Run the time analysis."""
    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        start_date, end_date = resolve_date_range(
            args
        )

        validate_completed_date(
            start_date,
            args.include_today,
        )

        validate_completed_date(
            end_date,
            args.include_today,
        )

        print()
        print("# Time Analysis")
        print()
        print(
            f"Input  : {args.input}"
        )
        print(
            f"Dates  : "
            f"{start_date.isoformat()} → "
            f"{end_date.isoformat()}"
        )
        print(
            "Mode   : "
            + (
                "INCLUDES CURRENT DAY"
                if args.include_today
                else "COMPLETED DAYS ONLY"
            )
        )

        records = read_daily_time(
            args.input,
            start_date,
            end_date,
        )

        result = analyze(
            records,
            start_date,
            end_date,
        )

        date_range_label = (
            f"{start_date.isoformat()}_"
            f"{end_date.isoformat()}"
        )

        csv_path = (
            args.output_dir
            / f"Time_Analysis_{date_range_label}.csv"
        )

        text_path = (
            args.output_dir
            / f"Time_Analysis_{date_range_label}.txt"
        )

        write_analysis_csv(
            result,
            csv_path,
        )

        write_text_report(
            result,
            text_path,
        )

        print_console_report(
            result,
            csv_path,
            text_path,
        )

        return 0

    except AnalysisError as exc:
        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    except OSError as exc:
        print(
            f"\nERROR: File operation failed: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())