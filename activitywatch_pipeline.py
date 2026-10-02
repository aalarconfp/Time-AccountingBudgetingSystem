# FILE: activitywatch_pipeline.py

"""Run the completed-day ActivityWatch -> Fact_Time pipeline.

The pipeline orchestrates the existing independent components:

1. activitywatch_raw_loader.py
2. fact_time_builder.py
3. fact_time_validator.py

The pipeline supports one or more explicit dates, a whole month, or the
default latest completed project-local date.

By default, the current local calendar day is never processed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from config.tracker_config import latest_completed_date


PROJECT_DIRECTORY = Path(__file__).resolve().parent

RAW_LOADER = PROJECT_DIRECTORY / "activitywatch_raw_loader.py"
FACT_TIME_BUILDER = PROJECT_DIRECTORY / "fact_time_builder.py"
FACT_TIME_VALIDATOR = PROJECT_DIRECTORY / "fact_time_validator.py"


class PipelineError(RuntimeError):
    """Raised when a pipeline stage fails."""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the completed-day ActivityWatch -> Fact_Time pipeline "
            "for one or more dates."
        )
    )

    parser.add_argument(
        "--date",
        dest="dates",
        action="append",
        metavar="YYYY-MM-DD",
        help=(
            "Process one calendar date. "
            "May be supplied multiple times."
        ),
    )

    parser.add_argument(
        "--month",
        dest="month",
        metavar="YYYY-MM",
        help=(
            "Process all completed dates in the specified month. "
            "The current project-local date is excluded."
        ),
    )

    return parser.parse_args()


def validate_script_paths() -> None:
    """Ensure all required pipeline scripts exist."""
    scripts = (
        RAW_LOADER,
        FACT_TIME_BUILDER,
        FACT_TIME_VALIDATOR,
    )

    missing = [
        str(path)
        for path in scripts
        if not path.is_file()
    ]

    if missing:
        missing_text = "\n".join(
            f"  - {path}"
            for path in missing
        )

        raise PipelineError(
            "Required pipeline script(s) not found:\n"
            f"{missing_text}"
        )


def parse_date(value: str) -> date:
    """Parse an ISO calendar date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def parse_month(value: str) -> tuple[int, int]:
    """Parse a YYYY-MM month value."""
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid month '{value}'. Expected YYYY-MM."
        ) from exc

    return parsed.year, parsed.month


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in a calendar month."""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    return (next_month - date(year, month, 1)).days


def resolve_dates(
    explicit_dates: list[str] | None,
    month: str | None,
) -> list[date]:
    """Resolve requested dates into sorted unique completed dates."""
    if explicit_dates and month:
        raise PipelineError(
            "Use either --date or --month, not both."
        )

    latest = latest_completed_date()

    if explicit_dates:
        resolved = [
            parse_date(value)
            for value in explicit_dates
        ]

        unique_dates = sorted(set(resolved))

        future_dates = [
            target
            for target in unique_dates
            if target > latest
        ]

        if future_dates:
            formatted = ", ".join(
                target.isoformat()
                for target in future_dates
            )
            raise PipelineError(
                "The following dates are not completed project-local "
                f"dates: {formatted}"
            )

        return unique_dates

    if month:
        year, month_number = parse_month(month)

        total_days = days_in_month(
            year,
            month_number,
        )

        month_dates = [
            date(
                year,
                month_number,
                day,
            )
            for day in range(1, total_days + 1)
        ]

        return [
            target
            for target in month_dates
            if target <= latest
        ]

    return [latest]


def run_stage(
    stage_number: int,
    total_stages: int,
    name: str,
    script_path: Path,
    target_date: date,
) -> None:
    """Run one pipeline stage for the target date."""
    command = [
        sys.executable,
        str(script_path),
        "--date",
        target_date.isoformat(),
    ]

    print()
    print("=" * 72)
    print(
        f"STAGE {stage_number}/{total_stages}: {name}"
    )
    print("=" * 72)
    print(
        f"Command: "
        f"{Path(sys.executable).name} "
        f"{script_path.name} "
        f"--date {target_date.isoformat()}"
    )
    print()

    result = subprocess.run(
        command,
        cwd=PROJECT_DIRECTORY,
        check=False,
    )

    if result.returncode != 0:
        raise PipelineError(
            f"{name} failed with exit code "
            f"{result.returncode}."
        )

    print()
    print(
        f"PASS: {name} completed successfully."
    )


def run_date_pipeline(target_date: date) -> None:
    """Run all pipeline stages for one date."""
    print()
    print("#" * 72)
    print(
        f"PROCESSING DATE: {target_date.isoformat()}"
    )
    print("#" * 72)

    run_stage(
        stage_number=1,
        total_stages=3,
        name="ActivityWatch Raw Loader",
        script_path=RAW_LOADER,
        target_date=target_date,
    )

    run_stage(
        stage_number=2,
        total_stages=3,
        name="Fact_Time Builder",
        script_path=FACT_TIME_BUILDER,
        target_date=target_date,
    )

    run_stage(
        stage_number=3,
        total_stages=3,
        name="Fact_Time Validator",
        script_path=FACT_TIME_VALIDATOR,
        target_date=target_date,
    )


def print_batch_summary(
    requested_dates: list[date],
    successful_dates: list[date],
    failed_dates: list[date],
) -> None:
    """Print the aggregate pipeline result."""
    print()
    print("=" * 72)
    print("=== ActivityWatch -> Fact_Time Pipeline Summary ===")
    print("=" * 72)

    print(
        f"Requested dates : {len(requested_dates)}"
    )
    print(
        f"Successful      : {len(successful_dates)}"
    )
    print(
        f"Failed          : {len(failed_dates)}"
    )
    print()

    if successful_dates:
        print("Successful dates:")
        for target in successful_dates:
            print(
                f"  PASS  {target.isoformat()}"
            )

    if failed_dates:
        print()
        print("Failed dates:")
        for target in failed_dates:
            print(
                f"  FAIL  {target.isoformat()}"
            )

    print()

    if failed_dates:
        print(
            "RESULT: ActivityWatch -> Fact_Time "
            "pipeline completed with failures."
        )
    else:
        print(
            "RESULT: ActivityWatch -> Fact_Time "
            "pipeline completed successfully."
        )


def main() -> int:
    """Run the requested ActivityWatch pipeline dates."""
    print("# ActivityWatch -> Fact_Time Pipeline")
    print()

    try:
        arguments = parse_arguments()
        validate_script_paths()

        target_dates = resolve_dates(
            explicit_dates=arguments.dates,
            month=arguments.month,
        )

        if not target_dates:
            raise PipelineError(
                "No completed dates were found for the requested range."
            )

        print(
            f"Requested dates : {len(target_dates)}"
        )
        print(
            "Mode            : COMPLETED DAYS ONLY"
        )
        print(
            "Today           : excluded by default"
        )
        print(
            f"Python          : {sys.executable}"
        )
        print(
            f"Project         : {PROJECT_DIRECTORY}"
        )
        print()
        print("Dates:")
        for target in target_dates:
            print(
                f"  - {target.isoformat()}"
            )

        successful_dates: list[date] = []
        failed_dates: list[date] = []

        for target_date in target_dates:
            try:
                run_date_pipeline(target_date)
            except PipelineError as exc:
                failed_dates.append(target_date)

                print()
                print(
                    f"DATE FAILED: "
                    f"{target_date.isoformat()}"
                )
                print(
                    f"Reason: {exc}",
                    file=sys.stderr,
                )

                continue

            successful_dates.append(target_date)

        print_batch_summary(
            requested_dates=target_dates,
            successful_dates=successful_dates,
            failed_dates=failed_dates,
        )

        return 1 if failed_dates else 0

    except KeyboardInterrupt:
        print()
        print(
            "PIPELINE STOPPED: Cancelled by user."
        )
        return 130

    except PipelineError as exc:
        print()
        print(
            f"PIPELINE FAILED: {exc}",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:
        print()
        print(
            f"PIPELINE FAILED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())