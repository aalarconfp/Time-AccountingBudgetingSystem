# iphone_screen_time_rebuild.py

"""Zero-cost rebuild of existing Apple Screen Time extractions.

This utility never calls OpenAI.

It recalculates durations from the original AI display evidence and can
apply explicitly documented evidence corrections when the previous AI
extraction misread a screenshot.

Canonical AI_Extraction.json files are never modified.

Corrected output is written to:
    AI_Extraction_Candidate.json

Correction evidence is read from:
    AI_Evidence_Corrections.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent

RAW_OUTPUT = (
    PROJECT_ROOT
    / "output"
    / "Raw"
    / "AppleScreenTime"
    / "iPhone"
)

UNRESOLVED_CATEGORY_NAME = "Apple Screen Time Unresolved"

CORRECTIONS_FILENAME = "AI_Evidence_Corrections.json"


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild existing Apple Screen Time "
            "extractions without API access."
        )
    )

    parser.add_argument(
        "--month",
        required=True,
        help="Month in YYYY-MM format.",
    )

    parser.add_argument(
        "--date",
        action="append",
        dest="dates",
        help=(
            "Process one date. Repeat --date to process "
            "multiple dates. If omitted, process all "
            "available dates in the month."
        ),
    )

    return parser.parse_args()


def parse_month(value: str) -> tuple[int, int]:
    """Validate a YYYY-MM month."""
    try:
        year_text, month_text = value.split("-")

        if len(year_text) != 4 or len(month_text) != 2:
            raise ValueError

        year = int(year_text)
        month = int(month_text)

        if not 1 <= month <= 12:
            raise ValueError

        return year, month

    except ValueError as exc:
        raise ValueError(
            f"Invalid month '{value}'. Expected YYYY-MM."
        ) from exc


def parse_date(value: str) -> date:
    """Validate an ISO calendar date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def list_date_directories(
    month: str,
    target_dates: list[str] | None,
) -> list[Path]:
    """Return Screen Time output directories for requested dates."""
    parse_month(month)

    month_directory = RAW_OUTPUT / month

    if target_dates:
        directories: list[Path] = []
        seen_dates: set[str] = set()

        for target_date in target_dates:
            parsed_date = parse_date(target_date)

            if parsed_date.strftime("%Y-%m") != month:
                raise ValueError(
                    f"{target_date} is outside {month}."
                )

            if target_date in seen_dates:
                continue

            seen_dates.add(target_date)

            directories.append(
                month_directory / target_date
            )

        return directories

    if not month_directory.exists():
        return []

    return sorted(
        path
        for path in month_directory.iterdir()
        if path.is_dir()
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            path.name,
        )
    )


def duration_to_seconds(duration: str) -> int:
    """Convert an Apple Screen Time duration to seconds."""
    value = (
        str(duration)
        .strip()
        .lower()
        .replace(" ", "")
    )

    if not value:
        raise ValueError("Empty duration.")

    matches = re.findall(
        r"(\d+)([hms])",
        value,
    )

    if not matches:
        raise ValueError(
            f"Unsupported duration: '{duration}'."
        )

    reconstructed = "".join(
        f"{number}{unit}"
        for number, unit in matches
    )

    if reconstructed != value:
        raise ValueError(
            f"Unsupported duration: '{duration}'."
        )

    components = {
        "h": 0,
        "m": 0,
        "s": 0,
    }

    for number, unit in matches:
        if components[unit] != 0:
            raise ValueError(
                f"Duplicate duration component "
                f"in '{duration}'."
            )

        components[unit] = int(number)

    if components["m"] >= 60:
        raise ValueError(
            f"Invalid minutes in '{duration}'."
        )

    if components["s"] >= 60:
        raise ValueError(
            f"Invalid seconds in '{duration}'."
        )

    return (
        components["h"] * 3600
        + components["m"] * 60
        + components["s"]
    )


def seconds_to_duration(seconds: int) -> str:
    """Format seconds using Apple-style duration units."""
    if seconds < 0:
        raise ValueError(
            "Duration cannot be negative."
        )

    hours, remainder = divmod(
        seconds,
        3600,
    )

    minutes, remaining_seconds = divmod(
        remainder,
        60,
    )

    parts: list[str] = []

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if remaining_seconds:
        parts.append(f"{remaining_seconds}s")

    if not parts:
        parts.append("0s")

    return " ".join(parts)


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object."""
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def save_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Save formatted JSON."""
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def calculate_hash(path: Path) -> str:
    """Calculate SHA-256 for a file."""
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def find_category(
    extraction: dict[str, Any],
    category_name: str,
) -> dict[str, Any]:
    """Find an Apple category by name."""
    normalized_name = (
        category_name.strip().lower()
    )

    for category in extraction.get(
        "categories",
        [],
    ):
        current_name = str(
            category.get(
                "apple_category",
                "",
            )
        ).strip().lower()

        if current_name == normalized_name:
            return category

    raise ValueError(
        f"Category not found: '{category_name}'."
    )


def apply_corrections(
    extraction: dict[str, Any],
    correction_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:
    """Apply explicitly documented evidence corrections.

    Corrections are idempotent:
    - old_value -> new_value applies the correction.
    - new_value -> new_value is treated as already applied.
    - old_value null adds a category omitted by the AI extraction.
    - any other value is a genuine conflict.
    """
    if not correction_path.exists():
        return extraction, []

    corrections_document = load_json(
        correction_path
    )

    expected_date = corrections_document.get(
        "date"
    )

    actual_date = extraction.get(
        "date"
    )

    if expected_date != actual_date:
        raise ValueError(
            "Correction date does not match "
            f"extraction date: "
            f"{expected_date} != {actual_date}."
        )

    corrections = corrections_document.get(
        "corrections",
        [],
    )

    rebuilt = json.loads(
        json.dumps(extraction)
    )

    applied: list[dict[str, Any]] = []

    for correction in corrections:
        path = str(
            correction.get(
                "path",
                "",
            )
        )

        old_value = correction.get(
            "old_value"
        )

        new_value = correction.get(
            "new_value"
        )

        reason = str(
            correction.get(
                "reason",
                "",
            )
        )

        match = re.fullmatch(
            r"categories\[(.+)\]\.duration_display",
            path,
        )

        if not match:
            raise ValueError(
                f"Unsupported correction path: "
                f"'{path}'."
            )

        category_name = match.group(1)

        # old_value null documents a category that is visible in the
        # screenshot but was omitted by the AI extraction.
        if old_value is None:
            try:
                category = find_category(
                    rebuilt,
                    category_name,
                )
            except ValueError:
                rebuilt.setdefault(
                    "categories",
                    [],
                ).append(
                    {
                        "apple_category": category_name,
                        "duration_display": new_value,
                    }
                )

                applied.append(
                    {
                        "path": path,
                        "old_value": old_value,
                        "new_value": new_value,
                        "reason": reason,
                        "status": "added",
                    }
                )

                continue
        else:
            category = find_category(
                rebuilt,
                category_name,
            )

        actual_value = category.get(
            "duration_display"
        )

        if actual_value == old_value:
            category[
                "duration_display"
            ] = new_value

            applied.append(
                {
                    "path": path,
                    "old_value": old_value,
                    "new_value": new_value,
                    "reason": reason,
                    "status": "applied",
                }
            )

            continue

        if actual_value == new_value:
            applied.append(
                {
                    "path": path,
                    "old_value": old_value,
                    "new_value": new_value,
                    "reason": reason,
                    "status": "already_applied",
                }
            )

            continue

        raise ValueError(
            f"Correction for "
            f"'{category_name}' expected either "
            f"'{old_value}' or already-correct "
            f"'{new_value}', but existing value is "
            f"'{actual_value}'."
        )

    return rebuilt, applied


def rebuild_extraction(
    extraction: dict[str, Any],
    corrections: list[dict[str, Any]],
) -> tuple[
    dict[str, Any],
    list[str],
]:
    """Recalculate all duration values."""
    rebuilt = json.loads(
        json.dumps(extraction)
    )

    warnings: list[str] = []

    total_display = rebuilt.get(
        "total_screen_time_display"
    )

    if not total_display:
        raise ValueError(
            "Missing total_screen_time_display."
        )

    total_seconds = duration_to_seconds(
        total_display
    )

    rebuilt[
        "total_screen_time_sec"
    ] = total_seconds

    category_total = 0

    for category in rebuilt.get(
        "categories",
        [],
    ):
        display = category.get(
            "duration_display"
        )

        if not display:
            raise ValueError(
                "Category is missing "
                "duration_display."
            )

        seconds = duration_to_seconds(
            display
        )

        category[
            "duration_sec"
        ] = seconds

        category_total += seconds

    if category_total <= 0:
        raise ValueError(
            "Visible category total is zero."
        )

    social_app_total = 0

    for app in rebuilt.get(
        "social_apps",
        [],
    ):
        display = app.get(
            "duration_display"
        )

        if not display:
            raise ValueError(
                "Social app is missing "
                "duration_display."
            )

        seconds = duration_to_seconds(
            display
        )

        app[
            "duration_sec"
        ] = seconds

        social_app_total += seconds

    difference = (
        total_seconds
        - category_total
    )

    unresolved_seconds = 0

    if difference > 0:
        reconciliation_status = (
            "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES"
        )

        unresolved_seconds = difference

        warnings.append(
            "Apple headline Screen Time exceeds "
            "the visible category total. The "
            f"difference of "
            f"{seconds_to_duration(difference)} "
            "is preserved as derived Apple Screen "
            "Time Unresolved time."
        )

    elif difference < 0:
        reconciliation_status = (
            "VISIBLE_CATEGORIES_EXCEED_HEADLINE"
        )

        warnings.append(
            "Visible Apple category time exceeds "
            "the headline Screen Time by "
            f"{seconds_to_duration(abs(difference))}. "
            "The discrepancy is preserved as an "
            "Apple reconciliation anomaly."
        )

    else:
        reconciliation_status = "MATCH"

    social_category_seconds = next(
        (
            int(
                category[
                    "duration_sec"
                ]
            )
            for category in rebuilt.get(
                "categories",
                [],
            )
            if (
                str(
                    category[
                        "apple_category"
                    ]
                )
                .strip()
                .lower()
                == "social"
            )
        ),
        None,
    )

    social_difference = None

    if social_category_seconds is not None:
        social_difference = (
            social_category_seconds
            - social_app_total
        )

        if (
            rebuilt.get(
                "social_detail_complete",
                False,
            )
            and social_difference != 0
        ):
            warnings.append(
                "Visible Social app detail does "
                "not exactly reconcile to the Social "
                "category total. Social category time "
                "remains authoritative."
            )

    rebuilt[
        "category_total_sec"
    ] = category_total

    rebuilt[
        "category_total_display"
    ] = seconds_to_duration(
        category_total
    )

    rebuilt[
        "reconciliation_difference_sec"
    ] = difference

    rebuilt[
        "reconciliation_difference_display"
    ] = seconds_to_duration(
        abs(difference)
    )

    rebuilt[
        "reconciliation_status"
    ] = reconciliation_status

    rebuilt[
        "unresolved_screen_time_sec"
    ] = unresolved_seconds

    rebuilt[
        "unresolved_screen_time_display"
    ] = seconds_to_duration(
        unresolved_seconds
    )

    rebuilt[
        "unresolved_screen_time_allocation_type"
    ] = (
        "Derived"
        if unresolved_seconds
        else None
    )

    rebuilt[
        "unresolved_screen_time_category"
    ] = (
        UNRESOLVED_CATEGORY_NAME
        if unresolved_seconds
        else None
    )

    rebuilt[
        "unresolved_screen_time_evidence"
    ] = (
        "Difference between Apple headline "
        "Screen Time and visible Apple category "
        "totals."
        if unresolved_seconds
        else None
    )

    rebuilt[
        "social_app_total_sec"
    ] = social_app_total

    rebuilt[
        "social_app_total_display"
    ] = seconds_to_duration(
        social_app_total
    )

    rebuilt[
        "social_category_difference_sec"
    ] = social_difference

    rebuilt[
        "social_category_difference_display"
    ] = (
        seconds_to_duration(
            abs(social_difference)
        )
        if social_difference is not None
        else None
    )

    rebuilt[
        "evidence_corrections"
    ] = corrections

    rebuilt[
        "rebuild"
    ] = {
        "method": (
            "deterministic_local_rebuild"
        ),
        "api_calls": 0,
        "cost_usd": 0.0,
        "source": (
            "existing AI_Extraction.json"
        ),
        "correction_count": len(
            corrections
        ),
    }

    rebuilt[
        "warnings"
    ] = list(
        dict.fromkeys(warnings)
    )

    return rebuilt, rebuilt["warnings"]


def build_candidate_metadata(
    target_date: str,
    extraction_path: Path,
    original_metadata: dict[str, Any] | None,
    correction_path: Path,
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build candidate metadata."""
    metadata: dict[str, Any] = {
        "date": target_date,
        "status": "candidate",
        "rebuild": {
            "method": (
                "deterministic_local_rebuild"
            ),
            "api_calls": 0,
            "estimated_cost_usd": 0.0,
            "source": (
                "existing AI_Extraction.json"
            ),
        },
        "source_extraction_sha256": (
            calculate_hash(
                extraction_path
            )
        ),
        "correction_file": (
            correction_path.name
            if correction_path.exists()
            else None
        ),
        "corrections_applied": corrections,
    }

    if original_metadata:
        metadata[
            "source_metadata"
        ] = {
            "content_hash": (
                original_metadata.get(
                    "content_hash"
                )
            ),
            "model": (
                original_metadata.get(
                    "model"
                )
            ),
            "original_usage": (
                original_metadata.get(
                    "usage"
                )
            ),
        }

    return metadata


def process_date(
    directory: Path,
) -> str:
    """Rebuild one date."""
    target_date = directory.name

    extraction_path = (
        directory
        / "AI_Extraction.json"
    )

    metadata_path = (
        directory
        / "AI_Metadata.json"
    )

    correction_path = (
        directory
        / CORRECTIONS_FILENAME
    )

    candidate_path = (
        directory
        / "AI_Extraction_Candidate.json"
    )

    candidate_metadata_path = (
        directory
        / "AI_Metadata_Candidate.json"
    )

    if not extraction_path.exists():
        print(
            f"{target_date} | SKIPPED | "
            "No AI_Extraction.json"
        )
        return "SKIPPED"

    extraction = load_json(
        extraction_path
    )

    original_metadata = None

    if metadata_path.exists():
        original_metadata = load_json(
            metadata_path
        )

    corrected_extraction, corrections = (
        apply_corrections(
            extraction,
            correction_path,
        )
    )

    rebuilt, warnings = rebuild_extraction(
        corrected_extraction,
        corrections,
    )

    candidate_metadata = (
        build_candidate_metadata(
            target_date=target_date,
            extraction_path=extraction_path,
            original_metadata=(
                original_metadata
            ),
            correction_path=correction_path,
            corrections=corrections,
        )
    )

    save_json(
        candidate_path,
        rebuilt,
    )

    save_json(
        candidate_metadata_path,
        candidate_metadata,
    )

    total_seconds = int(
        rebuilt[
            "total_screen_time_sec"
        ]
    )

    category_seconds = int(
        rebuilt[
            "category_total_sec"
        ]
    )

    unresolved_seconds = int(
        rebuilt[
            "unresolved_screen_time_sec"
        ]
    )

    print(
        f"{target_date} | REBUILT | "
        "0 API calls | $0.000000"
    )

    print(
        f"  Headline Screen Time : "
        f"{seconds_to_duration(total_seconds)}"
    )

    print(
        f"  Visible categories   : "
        f"{seconds_to_duration(category_seconds)}"
    )

    print(
        f"  Unresolved Apple     : "
        f"{seconds_to_duration(unresolved_seconds)}"
    )

    print(
        f"  Reconciliation       : "
        f"{rebuilt['reconciliation_status']}"
    )

    if corrections:
        applied_count = sum(
            correction.get("status")
            == "applied"
            for correction in corrections
        )

        already_applied_count = sum(
            correction.get("status")
            == "already_applied"
            for correction in corrections
        )

        print(
            "  Evidence corrections: "
            f"{len(corrections)}"
        )

        if applied_count:
            print(
                f"    Applied            : "
                f"{applied_count}"
            )

        if already_applied_count:
            print(
                f"    Already applied    : "
                f"{already_applied_count}"
            )

        for correction in corrections:
            print(
                "    "
                f"{correction['path']}: "
                f"{correction['old_value']} "
                f"-> "
                f"{correction['new_value']} "
                f"({correction['status']})"
            )

    if warnings:
        print(
            f"  Review warnings      : "
            f"{len(warnings)}"
        )

        for warning in warnings:
            print(
                f"    WARNING: {warning}"
            )

    print(
        f"  Candidate            : "
        f"{candidate_path}"
    )

    return (
        "REVIEW"
        if warnings
        else "REBUILT"
    )


def format_requested_dates(
    target_dates: list[str] | None,
) -> str:
    """Format the requested date selection."""
    if not target_dates:
        return "all available dates"

    return ", ".join(target_dates)


def main() -> int:
    """Run zero-cost local rebuild."""
    args = parse_arguments()

    print(
        "# iPhone Screen Time Local Rebuild"
    )
    print()
    print(
        f"Month : {args.month}"
    )
    print(
        "Dates : "
        f"{format_requested_dates(args.dates)}"
    )
    print(
        "API   : 0 calls"
    )
    print(
        "Cost  : $0.000000"
    )
    print()

    counts = {
        "REBUILT": 0,
        "REVIEW": 0,
        "SKIPPED": 0,
        "FAILED": 0,
    }

    try:
        directories = list_date_directories(
            args.month,
            args.dates,
        )

        if not directories:
            print(
                "No Screen Time output dates "
                "were found."
            )
            return 1

        for directory in directories:
            try:
                status = process_date(
                    directory
                )

                counts[status] += 1

            except Exception as exc:
                counts["FAILED"] += 1

                print(
                    f"{directory.name} | FAILED | "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

        print()
        print(
            "=== LOCAL REBUILD SUMMARY ==="
        )

        for status, count in counts.items():
            print(
                f"{status:<10}: {count}"
            )

        print(
            "API calls : 0"
        )

        print(
            "Cost      : $0.000000"
        )

        if counts["FAILED"]:
            print()
            print(
                "RESULT: LOCAL REBUILD FAILED."
            )
            return 1

        if counts["REVIEW"]:
            print()
            print(
                "RESULT: LOCAL REBUILD PASSED "
                "WITH REVIEW."
            )
            return 0

        print()
        print(
            "RESULT: LOCAL REBUILD PASSED."
        )

        return 0

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        print(
            "RESULT: LOCAL REBUILD FAILED.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())