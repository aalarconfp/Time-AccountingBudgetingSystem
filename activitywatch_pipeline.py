# G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker\activitywatch_pipeline.py

"""Run the completed-day ActivityWatch → Fact_Time pipeline.

The pipeline orchestrates the existing independent components:

1. activitywatch_raw_loader.py
2. fact_time_builder.py
3. fact_time_validator.py

The target date is resolved once at startup using the centralized
completed-day rule from tracker_config.py. This guarantees that all
three stages operate on exactly the same date.

By default, the current local calendar day is never processed.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

from tracker_config import latest_completed_date


PROJECT_DIRECTORY = Path(__file__).resolve().parent

RAW_LOADER = PROJECT_DIRECTORY / "activitywatch_raw_loader.py"
FACT_TIME_BUILDER = PROJECT_DIRECTORY / "fact_time_builder.py"
FACT_TIME_VALIDATOR = PROJECT_DIRECTORY / "fact_time_validator.py"


class PipelineError(RuntimeError):
    """Raised when a pipeline stage fails."""


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


def print_pipeline_summary(
    target_date: date,
) -> None:
    """Print the final pipeline result."""
    print()
    print("=" * 72)
    print("=== ActivityWatch Pipeline Summary ===")
    print("=" * 72)
    print(
        f"Date : {target_date.isoformat()}"
    )
    print(
        "Mode : COMPLETED DAYS ONLY"
    )
    print()
    print(
        "PASS  ActivityWatch Raw Loader"
    )
    print(
        "PASS  Fact_Time Builder"
    )
    print(
        "PASS  Fact_Time Validator"
    )
    print()
    print(
        "RESULT: ActivityWatch → Raw → Fact_Time "
        "pipeline completed successfully."
    )


def main() -> int:
    """Run the complete ActivityWatch pipeline."""
    print("# ActivityWatch → Fact_Time Pipeline")
    print()

    try:
        validate_script_paths()

        target_date = latest_completed_date()

        print(
            f"Target date : "
            f"{target_date.isoformat()}"
        )
        print(
            "Mode        : COMPLETED DAYS ONLY"
        )
        print(
            "Today       : excluded by default"
        )
        print(
            f"Python      : {sys.executable}"
        )
        print(
            f"Project     : {PROJECT_DIRECTORY}"
        )

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

        print_pipeline_summary(
            target_date
        )

        return 0

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