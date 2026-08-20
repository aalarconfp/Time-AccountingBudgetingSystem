# activitywatch_desktop.py

from __future__ import annotations

"""Desktop ActivityWatch collection entry point."""

import argparse
import subprocess
import sys
from pathlib import Path

from activitywatch_machine import DESKTOP, validate_machine


PROJECT_ROOT = Path(__file__).resolve().parent
RAW_LOADER = PROJECT_ROOT / "activitywatch_raw_loader.py"


def parse_args() -> argparse.Namespace:
    """Parse desktop collector arguments."""
    parser = argparse.ArgumentParser(
        description="Run ActivityWatch collection for the desktop PC."
    )

    parser.add_argument(
        "--date",
        help="Calendar date to collect in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--days",
        type=int,
        help="Collect the requested number of completed days.",
    )

    parser.add_argument(
        "--start-date",
        help="First calendar date for an inclusive collection range.",
    )

    parser.add_argument(
        "--end-date",
        help="Last calendar date for an inclusive collection range.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration of existing daily raw datasets.",
    )

    parser.add_argument(
        "--include-today",
        action="store_true",
        help="Allow collection of the current project-local day.",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate mutually exclusive and dependent arguments."""
    if args.date and (args.days or args.start_date or args.end_date):
        raise ValueError(
            "--date cannot be combined with --days, --start-date, "
            "or --end-date."
        )

    if args.days is not None and (args.start_date or args.end_date):
        raise ValueError(
            "--days cannot be combined with --start-date or --end-date."
        )

    if bool(args.start_date) != bool(args.end_date):
        raise ValueError(
            "--start-date and --end-date must be supplied together."
        )

    if args.days is not None and args.days < 1:
        raise ValueError("--days must be greater than zero.")


def build_command(args: argparse.Namespace) -> list[str]:
    """Build the shared raw-loader command."""
    command = [
        sys.executable,
        str(RAW_LOADER),
    ]

    if args.date:
        command.extend(["--date", args.date])

    if args.days is not None:
        command.extend(["--days", str(args.days)])

    if args.start_date:
        command.extend(["--start-date", args.start_date])

    if args.end_date:
        command.extend(["--end-date", args.end_date])

    if args.force:
        command.append("--force")

    if args.include_today:
        command.append("--include-today")

    return command


def main() -> int:
    """Validate the desktop environment and run the shared collector."""
    args = parse_args()

    try:
        validate_arguments(args)
        validate_machine(DESKTOP)

        if not RAW_LOADER.exists():
            raise FileNotFoundError(
                f"ActivityWatch raw loader not found: {RAW_LOADER}"
            )

        command = build_command(args)

        print("=== Desktop ActivityWatch Launcher ===")
        print(f"Expected hostname : {DESKTOP.hostname}")
        print(f"Source            : {DESKTOP.source}")
        print(f"Context           : {DESKTOP.context}")
        print(f"Python            : {sys.executable}")
        print(f"Raw loader        : {RAW_LOADER}")
        print()

        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
        )

        return result.returncode

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())