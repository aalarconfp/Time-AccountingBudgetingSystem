# G:\My Drive\Personal Life\Habit and Wellness\System_Tracker\period_process.py
"""
Canonical operational guide/orchestrator for a System Tracker period.

This script coordinates the existing source-specific programs without
replacing them. It deliberately stops for manual evidence and review.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

IPHONE_SCREENSHOTS = PROJECT_ROOT / "input" / "AppleScreenTime"
HABIT_SCREENSHOTS = PROJECT_ROOT / "input" / "Habit"

HABIT_ADJUSTMENTS = (
    PROJECT_ROOT / "input" / "Integrated" / "Habit_Manual_Adjustments.csv"
)
MANUAL_ADJUSTMENTS = (
    PROJECT_ROOT / "input" / "Integrated" / "Manual_Adjustments.csv"
)
CLASSIFICATION_WEIGHTS = (
    PROJECT_ROOT / "input" / "Integrated" / "Classification_Weights.csv"
)
CLASSIFICATION_REMOVALS = (
    PROJECT_ROOT
    / "output"
    / "Integrated"
    / "Analysis"
    / "Human_Review"
    / "Integration_Classification_Removals.csv"
)


class ProcessError(RuntimeError):
    """Raised when an operational stage cannot continue."""


@dataclass(frozen=True)
class Period:
    """Inclusive analysis period."""

    start: date
    end: date

    @property
    def month(self) -> str:
        return self.start.strftime("%Y-%m")

    @property
    def dates(self) -> list[date]:
        return [
            self.start + timedelta(days=offset)
            for offset in range((self.end - self.start).days + 1)
        ]


def parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD date."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def require_period(
    start: date | None,
    end: date | None,
) -> Period:
    """Validate and return the requested period."""
    if start is None or end is None:
        raise ProcessError(
            "--start-date and --end-date are required."
        )
    if end < start:
        raise ProcessError("End date cannot precede start date.")
    return Period(start=start, end=end)


def script(name: str) -> Path:
    """Return an existing project script."""
    path = PROJECT_ROOT / name
    if not path.is_file():
        raise ProcessError(f"Required script does not exist: {path}")
    return path


def run_script(name: str, arguments: list[str]) -> None:
    """Execute one existing project program."""
    command = [sys.executable, str(script(name)), *arguments]

    print()
    print("=" * 76)
    print(f"RUN: {name}")
    print("=" * 76)
    print(" ".join(f'"{item}"' if " " in item else item for item in command))
    print()

    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)

    if result.returncode != 0:
        raise ProcessError(
            f"{name} failed with exit code {result.returncode}."
        )

    print(f"PASS: {name}")


def header(title: str, period: Period) -> None:
    """Print a stage header."""
    print()
    print("=" * 76)
    print(title)
    print("=" * 76)
    print(f"Period: {period.start} -> {period.end}")
    print(f"Days:   {len(period.dates)}")
    print(f"Month:  {period.month}")
    print()


def stage_laptop(period: Period) -> None:
    """Collect ActivityWatch data on the laptop."""
    header("STAGE 1 — LAPTOP", period)
    run_script(
        "activitywatch_laptop.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--force",
        ],
    )


def stage_desktop(period: Period) -> None:
    """Collect ActivityWatch data on the desktop."""
    header("STAGE 2 — DESKTOP", period)
    run_script(
        "activitywatch_desktop.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--force",
        ],
    )


def stage_evidence(period: Period) -> None:
    """Guide and validate the manual screenshot checkpoint."""
    header("STAGE 3 — MANUAL EVIDENCE", period)

    print("iPhone Screen Time:")
    print(IPHONE_SCREENSHOTS / period.month)
    print()
    print("Habit:")
    print(HABIT_SCREENSHOTS / period.month)
    print()
    print("Create one YYYY-MM-DD directory for each date.")
    print("Save the original screenshots in those directories.")
    print()

    input("Press ENTER after screenshots have been saved...")

    missing_iphone = []
    missing_habit = []

    for target in period.dates:
        date_text = target.isoformat()
        if not (IPHONE_SCREENSHOTS / period.month / date_text).is_dir():
            missing_iphone.append(date_text)
        if not (HABIT_SCREENSHOTS / period.month / date_text).is_dir():
            missing_habit.append(date_text)

    if missing_iphone:
        raise ProcessError(
            "Missing iPhone screenshot directories: "
            + ", ".join(missing_iphone)
        )

    if missing_habit:
        raise ProcessError(
            "Missing Habit screenshot directories: "
            + ", ".join(missing_habit)
        )

    print("PASS: Screenshot directories exist for every date.")


def stage_source_processing(period: Period) -> None:
    """Process ActivityWatch, iPhone, Habit, and taxonomy."""
    header("STAGE 4 — SOURCE PROCESSING", period)

    run_script(
        "activitywatch_pipeline.py",
        ["--month", period.month],
    )

    for target in period.dates:
        run_script(
            "iphone_screen_time_ingest.py",
            [
                "--month",
                period.month,
                "--date",
                target.isoformat(),
                "--force",
            ],
        )

    iphone_dates = []
    for target in period.dates:
        iphone_dates.extend(["--date", target.isoformat()])

    run_script(
        "iphone_screen_time_builder.py",
        [
            "--month",
            period.month,
            *iphone_dates,
            "--force",
        ],
    )

    run_script(
        "habit_offdevice_ingest.py",
        ["--month", period.month, "--force"],
    )

    habit_dates = []
    for target in period.dates:
        habit_dates.extend(["--date", target.isoformat()])

    run_script(
        "habit_offdevice_builder.py",
        [
            "--month",
            period.month,
            *habit_dates,
            "--force",
        ],
    )

    run_script("build_time_taxonomy.py", [])


def stage_consolidation(period: Period) -> None:
    """Run preliminary cross-source consolidation."""
    header("STAGE 5 — CONSOLIDATION ANALYSIS", period)

    run_script(
        "integration_analysis.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--unaccounted-target-hours",
            "3",
        ],
    )

    print()
    print("Consolidation diagnostics complete.")
    print("Next step: manual review.")


def stage_review(period: Period) -> None:
    """Pause for human integration review."""
    header("STAGE 6 — MANUAL REVIEW", period)

    print("Review/edit as applicable:")
    print(f"  {HABIT_ADJUSTMENTS}")
    print(f"  {MANUAL_ADJUSTMENTS}")
    print(f"  {CLASSIFICATION_WEIGHTS}")
    print()
    print("Review generated classification removals:")
    print(f"  {CLASSIFICATION_REMOVALS}")
    print()
    print("Do not manually edit generated Final Analysis CSVs.")
    print()

    input("Press ENTER after manual review is complete...")


def stage_manual_adjustments(period: Period) -> None:
    """Apply reviewed Habit adjustments."""
    header("STAGE 7 — APPLY MANUAL ADJUSTMENTS", period)

    if not HABIT_ADJUSTMENTS.is_file():
        print("Habit_Manual_Adjustments.csv not found; skipping.")
        return

    run_script(
        "habit_manual_adjustments.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--adjustment-file",
            str(HABIT_ADJUSTMENTS),
            "--force",
        ],
    )


def stage_integrated_build(period: Period) -> None:
    """Build the canonical integrated daily dataset."""
    header("STAGE 8 — INTEGRATED DAILY TIME", period)

    run_script(
        "integrated_daily_time_builder.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--manual-input",
            str(MANUAL_ADJUSTMENTS),
            "--classification-input",
            str(CLASSIFICATION_WEIGHTS),
        ],
    )


def stage_final_analysis(period: Period) -> None:
    """Run final, detail, exploratory, and standard analysis."""
    header("STAGE 9 — FINAL ANALYSIS", period)

    arguments = [
        "--start-date",
        period.start.isoformat(),
        "--end-date",
        period.end.isoformat(),
        "--force",
    ]

    run_script("final_analysis.py", arguments)
    run_script("detail_analysis.py", arguments)
    run_script("exploratory_analysis.py", arguments)
    run_script("standard_report.py", arguments)


def stage_close(period: Period) -> None:
    """Run period-close validation."""
    header("STAGE 10 — PERIOD CLOSE", period)

    run_script(
        "period_close_validator_v5.py",
        [
            "--start-date",
            period.start.isoformat(),
            "--end-date",
            period.end.isoformat(),
            "--require-eda",
            "--require-standard-report",
        ],
    )

    print()
    print("=" * 76)
    print("PERIOD CLOSE PASSED")
    print("=" * 76)
    print("Archive the period and review Git changes before committing.")


STAGES = {
    "laptop": stage_laptop,
    "desktop": stage_desktop,
    "evidence": stage_evidence,
    "source-processing": stage_source_processing,
    "consolidation": stage_consolidation,
    "review": stage_review,
    "manual-adjustments": stage_manual_adjustments,
    "integrated-build": stage_integrated_build,
    "final-analysis": stage_final_analysis,
    "close": stage_close,
}

ORDERED_STAGES = list(STAGES)


def print_process(period: Period) -> None:
    """Print the canonical operational sequence."""
    header("SYSTEM TRACKER PERIOD PROCESS", period)

    print("1. LAPTOP")
    print("   activitywatch_laptop.py")
    print()
    print("2. DESKTOP")
    print("   activitywatch_desktop.py")
    print()
    print("3. MANUAL EVIDENCE")
    print("   iPhone Screen Time screenshots")
    print("   Habit screenshots")
    print()
    print("4. SOURCE PROCESSING")
    print("   ActivityWatch → Raw → Fact_Time → validation")
    print("   iPhone → extraction → source build")
    print("   Habit → extraction → source build")
    print("   Taxonomy validation")
    print()
    print("5. CONSOLIDATION")
    print("   integration_analysis.py")
    print()
    print("6. MANUAL REVIEW")
    print("   Habit_Manual_Adjustments.csv")
    print("   Manual_Adjustments.csv")
    print("   Classification_Weights.csv")
    print("   Integration_Classification_Removals.csv")
    print()
    print("7. FINAL ANALYSIS")
    print("   integrated_daily_time_builder.py")
    print("   final_analysis.py")
    print("   detail_analysis.py")
    print("   exploratory_analysis.py")
    print("   standard_report.py")
    print()
    print("8. PERIOD CLOSE")
    print("   period_close_validator_v5.py")
    print()
    print("9. ARCHIVE / GIT COMMIT")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Canonical System Tracker period process."
    )
    parser.add_argument(
        "--start-date",
        type=parse_date,
        required=True,
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        required=True,
    )
    parser.add_argument(
        "--stage",
        choices=ORDERED_STAGES,
        help="Run one stage only.",
    )
    parser.add_argument(
        "--run-from",
        choices=ORDERED_STAGES,
        help="Run every stage from this point through period close.",
    )
    parser.add_argument(
        "--show-process",
        action="store_true",
        help="Print the process without executing it.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the requested process."""
    arguments = parse_args()

    try:
        period = require_period(
            arguments.start_date,
            arguments.end_date,
        )

        if arguments.show_process:
            print_process(period)
            if not arguments.stage and not arguments.run_from:
                return 0

        if arguments.stage:
            STAGES[arguments.stage](period)
            return 0

        if arguments.run_from:
            start_index = ORDERED_STAGES.index(arguments.run_from)
            for stage_name in ORDERED_STAGES[start_index:]:
                STAGES[stage_name](period)
            return 0

        print_process(period)
        return 0

    except KeyboardInterrupt:
        print("\nPROCESS STOPPED BY USER.")
        return 130
    except ProcessError as exc:
        print(f"PROCESS FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"PROCESS FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())