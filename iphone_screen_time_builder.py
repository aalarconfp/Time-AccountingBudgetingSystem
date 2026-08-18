"""Build Fact and Daily iPhone Screen Time data.

The builder is deterministic and never calls an external API.

Apple category durations are authoritative.

For Apple's Social category, visible app detail is used to partition the
Social category when the app detail does not exceed the authoritative
category duration. A positive category residual is allocated as a derived
WhatsApp/Messaging proxy.

If visible Social app detail exceeds Apple's authoritative Social category,
the app detail is treated as supplemental evidence and the authoritative
Social category is used directly.

The difference between Apple's headline Screen Time and visible category
totals is handled as follows:

- Headline greater than visible categories:
  allocate the positive residual as derived Utilities /
  Screen Time / System time.

- Visible categories greater than headline:
  preserve the visible category total as an Apple reconciliation anomaly.
  No additional time is created and no negative residual is generated.

Canonical Apple Screen Time JSON files are read-only inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent

RAW_ROOT = (
    PROJECT_ROOT
    / "output"
    / "Raw"
    / "AppleScreenTime"
    / "iPhone"
)

FACT_ROOT = (
    PROJECT_ROOT
    / "output"
    / "Fact"
    / "Time"
    / "AppleScreenTime"
    / "iPhone"
)

DAILY_ROOT = (
    PROJECT_ROOT
    / "output"
    / "Daily"
    / "Time"
    / "AppleScreenTime"
    / "iPhone"
)

SOURCE = "iphone"

FACT_COLUMNS = [
    "Date",
    "Source",
    "Category",
    "Subcategory",
    "App",
    "Duration_sec",
    "Event_Count",
    "Allocation_Type",
    "Evidence_Type",
    "Evidence_Source",
]

DAILY_COLUMNS = [
    "Date",
    "Source",
    "Category",
    "Subcategory",
    "Duration_sec",
    "Event_Count",
    "Allocation_Type",
    "Evidence_Type",
    "Evidence_Source",
]

DERIVED_SCREEN_TIME_CATEGORY = "Utilities"
DERIVED_SCREEN_TIME_SUBCATEGORY = "Screen Time / System"

MESSAGING_CATEGORY = "Social Networking"
MESSAGING_SUBCATEGORY = "Messaging"
MESSAGING_PROXY_APP = "WhatsApp"

STATUS_NEW = "NEW"
STATUS_UNCHANGED = "UNCHANGED"
STATUS_CHANGED = "CHANGED"
STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class BuildResult:
    """Result for one processed date."""

    date: str
    status: str
    fact_path: Path
    daily_path: Path
    row_count: int
    total_seconds: int
    headline_seconds: int
    category_total_seconds: int
    reconciliation_difference_seconds: int


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build iPhone Screen Time Fact and Daily "
            "CSV outputs."
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
        help=(
            "Date in YYYY-MM-DD format. "
            "May be specified multiple times."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild existing outputs.",
    )

    return parser.parse_args()


def validate_month(value: str) -> tuple[int, int]:
    """Validate a YYYY-MM month."""
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise ValueError(
            f"Invalid month '{value}'. Expected YYYY-MM."
        )

    year, month = (
        int(part)
        for part in value.split("-")
    )

    if not 1 <= month <= 12:
        raise ValueError(
            f"Invalid month '{value}'."
        )

    return year, month


def validate_date(value: str) -> date:
    """Validate a YYYY-MM-DD date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def discover_dates(
    month: str,
    requested_dates: list[str] | None,
) -> list[str]:
    """Discover requested or available canonical dates."""
    validate_month(month)

    if requested_dates:
        result: list[str] = []

        for value in requested_dates:
            parsed = validate_date(value)

            if parsed.strftime("%Y-%m") != month:
                raise ValueError(
                    f"{value} is outside {month}."
                )

            result.append(value)

        return sorted(set(result))

    month_root = RAW_ROOT / month

    if not month_root.exists():
        return []

    dates: list[str] = []

    for directory in month_root.iterdir():
        if not directory.is_dir():
            continue

        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            directory.name,
        ):
            continue

        if (
            directory / "AI_Extraction.json"
        ).exists():
            dates.append(directory.name)

    return sorted(dates)


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON from disk."""
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def sha256(path: Path) -> str:
    """Calculate a file SHA-256 hash."""
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def duration_seconds(value: Any) -> int:
    """Validate and return a duration in seconds."""
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid duration: {value!r}"
        ) from exc

    if result < 0:
        raise ValueError(
            f"Duration cannot be negative: {result}"
        )

    return result


def canonical_path(
    target_date: str,
) -> Path:
    """Return the canonical extraction path."""
    return (
        RAW_ROOT
        / target_date[:7]
        / target_date
        / "AI_Extraction.json"
    )


def fact_path(
    target_date: str,
) -> Path:
    """Return the Fact output path."""
    return (
        FACT_ROOT
        / f"Fact_Time_{target_date}.csv"
    )


def daily_path(
    target_date: str,
) -> Path:
    """Return the Daily output path."""
    return (
        DAILY_ROOT
        / f"Daily_Time_{target_date}.csv"
    )


def metadata_path(
    target_date: str,
) -> Path:
    """Return the build metadata path."""
    return (
        DAILY_ROOT
        / f"Daily_Time_{target_date}.metadata.json"
    )


def find_social_category(
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Return Apple's authoritative Social category."""
    matches = [
        category
        for category in extraction.get(
            "categories",
            [],
        )
        if str(
            category.get(
                "apple_category",
                "",
            )
        ).strip().lower()
        == "social"
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one Apple Social category."
        )

    return matches[0]


def find_category(
    extraction: dict[str, Any],
    category_name: str,
) -> dict[str, Any]:
    """Return one Apple category by name."""
    matches = [
        category
        for category in extraction.get(
            "categories",
            [],
        )
        if str(
            category.get(
                "apple_category",
                "",
            )
        ).strip().lower()
        == category_name.lower()
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one '{category_name}' category."
        )

    return matches[0]


def calculate_category_total(
    extraction: dict[str, Any],
) -> int:
    """Calculate the sum of all visible Apple categories."""
    return sum(
        duration_seconds(
            category.get("duration_sec")
        )
        for category in extraction.get(
            "categories",
            [],
        )
    )


def calculate_headline_total(
    extraction: dict[str, Any],
) -> int:
    """Return Apple's headline Screen Time."""
    return duration_seconds(
        extraction.get(
            "total_screen_time_sec"
        )
    )


def build_non_social_rows(
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build rows for all visible non-Social Apple categories."""
    rows: list[dict[str, Any]] = []

    for category in extraction.get(
        "categories",
        [],
    ):
        category_name = str(
            category.get(
                "apple_category",
                "",
            )
        ).strip()

        if not category_name:
            raise ValueError(
                "Apple category has no name."
            )

        if category_name.lower() == "social":
            continue

        seconds = duration_seconds(
            category.get(
                "duration_sec"
            )
        )

        rows.append(
            {
                "Date": extraction["date"],
                "Source": SOURCE,
                "Category": category_name,
                "Subcategory": category_name,
                "App": "",
                "Duration_sec": seconds,
                "Event_Count": 1,
                "Allocation_Type": "Observed",
                "Evidence_Type": (
                    "Apple Screen Time Category"
                ),
                "Evidence_Source": "CATEGORIES",
            }
        )

    return rows


def build_authoritative_social_row(
    extraction: dict[str, Any],
    reason: str,
) -> list[dict[str, Any]]:
    """Build one authoritative Social category row."""
    social_category = find_social_category(
        extraction
    )

    social_seconds = duration_seconds(
        social_category.get(
            "duration_sec"
        )
    )

    return [
        {
            "Date": extraction["date"],
            "Source": SOURCE,
            "Category": MESSAGING_CATEGORY,
            "Subcategory": "Social Networking",
            "App": "",
            "Duration_sec": social_seconds,
            "Event_Count": 1,
            "Allocation_Type": "Observed",
            "Evidence_Type": (
                "Apple Social Category; "
                "Social App Detail Supplemental"
            ),
            "Evidence_Source": (
                "CATEGORIES; SOCIAL"
            ),
        }
    ]


def build_social_app_rows(
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    """Partition Apple's Social category using app detail when valid."""
    social_category = find_social_category(
        extraction
    )

    social_seconds = duration_seconds(
        social_category.get(
            "duration_sec"
        )
    )

    apps = extraction.get(
        "social_apps",
        [],
    )

    if not apps:
        raise ValueError(
            "Canonical extraction contains no Social app detail."
        )

    parsed_apps: list[tuple[str, int]] = []
    visible_seconds = 0

    for app in apps:
        app_name = str(
            app.get(
                "app",
                "",
            )
        ).strip()

        if not app_name:
            raise ValueError(
                "Social app has no name."
            )

        seconds = duration_seconds(
            app.get(
                "duration_sec"
            )
        )

        parsed_apps.append(
            (app_name, seconds)
        )
        visible_seconds += seconds

    residual = (
        social_seconds
        - visible_seconds
    )

    if residual < 0:
        return build_authoritative_social_row(
            extraction,
            reason=(
                "Visible Social app detail exceeds "
                "Apple Social category."
            ),
        )

    rows: list[dict[str, Any]] = []

    for app_name, seconds in parsed_apps:
        normalized_app = app_name.lower()

        if normalized_app in {
            "whatsapp",
            "messages",
            "messenger",
            "telegram",
            "signal",
        }:
            category = MESSAGING_CATEGORY
            subcategory = MESSAGING_SUBCATEGORY
        else:
            category = "Social Networking"
            subcategory = "Social Networking"

        rows.append(
            {
                "Date": extraction["date"],
                "Source": SOURCE,
                "Category": category,
                "Subcategory": subcategory,
                "App": app_name,
                "Duration_sec": seconds,
                "Event_Count": 1,
                "Allocation_Type": "Observed",
                "Evidence_Type": (
                    "Apple Social App Detail"
                ),
                "Evidence_Source": "SOCIAL",
            }
        )

    if residual:
        rows.append(
            {
                "Date": extraction["date"],
                "Source": SOURCE,
                "Category": MESSAGING_CATEGORY,
                "Subcategory": MESSAGING_SUBCATEGORY,
                "App": MESSAGING_PROXY_APP,
                "Duration_sec": residual,
                "Event_Count": 0,
                "Allocation_Type": "Derived",
                "Evidence_Type": (
                    "Apple Social Category Residual"
                ),
                "Evidence_Source": "SOCIAL",
            }
        )

    allocated_social = sum(
        int(row["Duration_sec"])
        for row in rows
    )

    if allocated_social != social_seconds:
        raise ValueError(
            "Social allocation does not reconcile: "
            f"{allocated_social} != "
            f"{social_seconds}."
        )

    return rows


def build_screen_time_residual_row(
    extraction: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a positive Apple headline Screen Time residual."""
    headline = calculate_headline_total(
        extraction
    )

    category_total = calculate_category_total(
        extraction
    )

    unresolved = duration_seconds(
        extraction.get(
            "unresolved_screen_time_sec",
            0,
        )
    )

    calculated = headline - category_total

    if calculated < 0:
        if unresolved != 0:
            raise ValueError(
                "Visible Apple categories exceed headline "
                "but unresolved Screen Time is not zero: "
                f"{unresolved}s."
            )

        return None

    if calculated != unresolved:
        raise ValueError(
            "Screen Time reconciliation does not match: "
            f"{headline} - {category_total} "
            f"!= {unresolved}."
        )

    if unresolved == 0:
        return None

    category = extraction.get(
        "unresolved_screen_time_category"
    )

    subcategory = extraction.get(
        "unresolved_screen_time_subcategory"
    )

    if category != DERIVED_SCREEN_TIME_CATEGORY:
        raise ValueError(
            "Unresolved Screen Time must be "
            f"classified as {DERIVED_SCREEN_TIME_CATEGORY}."
        )

    if subcategory != DERIVED_SCREEN_TIME_SUBCATEGORY:
        raise ValueError(
            "Unexpected Screen Time subcategory: "
            f"{subcategory}"
        )

    return {
        "Date": extraction["date"],
        "Source": SOURCE,
        "Category": category,
        "Subcategory": subcategory,
        "App": "",
        "Duration_sec": unresolved,
        "Event_Count": 0,
        "Allocation_Type": "Derived",
        "Evidence_Type": (
            "Apple Headline Screen Time Residual"
        ),
        "Evidence_Source": "TOTAL vs CATEGORIES",
    }


def build_fact_rows(
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the complete analytical Fact allocation."""
    rows = build_non_social_rows(
        extraction
    )

    rows.extend(
        build_social_app_rows(
            extraction
        )
    )

    residual = build_screen_time_residual_row(
        extraction
    )

    if residual is not None:
        rows.append(residual)

    return rows


def validate_fact_rows(
    extraction: dict[str, Any],
    rows: list[dict[str, Any]],
) -> int:
    """Validate Fact rows and return their analytical total."""
    headline = calculate_headline_total(
        extraction
    )

    category_total = calculate_category_total(
        extraction
    )

    actual = sum(
        duration_seconds(
            row["Duration_sec"]
        )
        for row in rows
    )

    expected = max(
        headline,
        category_total,
    )

    if actual != expected:
        raise ValueError(
            "Fact rows do not reconcile to analytical "
            f"Screen Time total: "
            f"{actual} != {expected}."
        )

    social_category = find_social_category(
        extraction
    )

    expected_social = duration_seconds(
        social_category[
            "duration_sec"
        ]
    )

    social_rows = [
        row
        for row in rows
        if (
            row["Evidence_Source"] == "SOCIAL"
            or row["Evidence_Source"] == "CATEGORIES; SOCIAL"
        )
        and row["Category"] == MESSAGING_CATEGORY
        and (
            row["Subcategory"]
            in {
                MESSAGING_SUBCATEGORY,
                "Social Networking",
            }
        )
    ]

    actual_social = sum(
        duration_seconds(
            row["Duration_sec"]
        )
        for row in social_rows
    )

    if actual_social != expected_social:
        raise ValueError(
            "Social allocation does not reconcile "
            f"to Apple Social: "
            f"{actual_social} != "
            f"{expected_social}."
        )

    return actual


def build_daily_rows(
    fact_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate Fact rows by category and subcategory."""
    grouped: dict[
        tuple[str, str, str, str],
        dict[str, Any],
    ] = {}

    for row in fact_rows:
        key = (
            row["Date"],
            row["Source"],
            row["Category"],
            row["Subcategory"],
        )

        if key not in grouped:
            grouped[key] = {
                "Date": row["Date"],
                "Source": row["Source"],
                "Category": row["Category"],
                "Subcategory": row[
                    "Subcategory"
                ],
                "Duration_sec": 0,
                "Event_Count": 0,
                "Allocation_Types": set(),
                "Evidence_Types": set(),
                "Evidence_Sources": set(),
            }

        target = grouped[key]

        target["Duration_sec"] += int(
            row["Duration_sec"]
        )

        target["Event_Count"] += int(
            row["Event_Count"]
        )

        target[
            "Allocation_Types"
        ].add(
            row["Allocation_Type"]
        )

        target[
            "Evidence_Types"
        ].add(
            row["Evidence_Type"]
        )

        target[
            "Evidence_Sources"
        ].add(
            row["Evidence_Source"]
        )

    rows: list[dict[str, Any]] = []

    for target in grouped.values():
        allocation_types = target[
            "Allocation_Types"
        ]

        if allocation_types == {"Observed"}:
            allocation_type = "Observed"
        elif allocation_types == {"Derived"}:
            allocation_type = "Derived"
        else:
            allocation_type = "Mixed"

        rows.append(
            {
                "Date": target["Date"],
                "Source": target["Source"],
                "Category": target["Category"],
                "Subcategory": target[
                    "Subcategory"
                ],
                "Duration_sec": target[
                    "Duration_sec"
                ],
                "Event_Count": target[
                    "Event_Count"
                ],
                "Allocation_Type": allocation_type,
                "Evidence_Type": "; ".join(
                    sorted(
                        target[
                            "Evidence_Types"
                        ]
                    )
                ),
                "Evidence_Source": "; ".join(
                    sorted(
                        target[
                            "Evidence_Sources"
                        ]
                    )
                ),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["Category"],
            row["Subcategory"],
        ),
    )


def serialize_csv(
    rows: list[dict[str, Any]],
    columns: list[str],
) -> bytes:
    """Serialize rows to deterministic CSV bytes."""
    buffer = StringIO(
        newline=""
    )

    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        extrasaction="raise",
        lineterminator="\n",
    )

    writer.writeheader()

    for row in rows:
        writer.writerow(row)

    return buffer.getvalue().encode(
        "utf-8"
    )


def write_if_changed(
    path: Path,
    content: bytes,
    force: bool,
) -> str:
    """Write content only when needed."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if path.exists():
        if path.read_bytes() == content:
            return STATUS_UNCHANGED

        path.write_bytes(content)
        return STATUS_CHANGED

    path.write_bytes(content)
    return STATUS_NEW


def write_metadata(
    target_date: str,
    extraction_path: Path,
    fact_file: Path,
    daily_file: Path,
    fact_rows: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
) -> None:
    """Write deterministic build metadata."""
    extraction = load_json(
        extraction_path
    )

    headline = calculate_headline_total(
        extraction
    )

    category_total = calculate_category_total(
        extraction
    )

    reconciliation_difference = (
        headline - category_total
    )

    if reconciliation_difference > 0:
        reconciliation_status = (
            "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES"
        )
    elif reconciliation_difference < 0:
        reconciliation_status = (
            "VISIBLE_CATEGORIES_EXCEED_HEADLINE"
        )
    else:
        reconciliation_status = "RECONCILED"

    metadata = {
        "date": target_date,
        "source": SOURCE,
        "builder": "iphone_screen_time_builder.py",
        "api_calls": 0,
        "estimated_cost_usd": 0.0,
        "canonical_extraction_sha256": (
            sha256(extraction_path)
        ),
        "reconciliation": {
            "headline_seconds": headline,
            "visible_category_total_seconds": (
                category_total
            ),
            "difference_seconds": (
                reconciliation_difference
            ),
            "status": reconciliation_status,
            "anomaly_preserved": (
                reconciliation_difference < 0
            ),
            "unresolved_allocated_seconds": (
                max(reconciliation_difference, 0)
            ),
        },
        "fact": {
            "path": str(fact_file),
            "rows": len(fact_rows),
            "duration_sec": sum(
                int(row["Duration_sec"])
                for row in fact_rows
            ),
        },
        "daily": {
            "path": str(daily_file),
            "rows": len(daily_rows),
            "duration_sec": sum(
                int(row["Duration_sec"])
                for row in daily_rows
            ),
        },
        "allocation_rules": {
            "category_authority": (
                "Apple Screen Time category durations "
                "are authoritative."
            ),
            "social_category": {
                "method": (
                    "Partition Apple Social category "
                    "using visible Social app detail "
                    "when app detail does not exceed "
                    "the authoritative category."
                ),
                "excess_behavior": (
                    "If visible Social app detail exceeds "
                    "the Social category, the app detail "
                    "is supplemental and the Social "
                    "category is used directly."
                ),
                "residual": {
                    "category": MESSAGING_CATEGORY,
                    "subcategory": MESSAGING_SUBCATEGORY,
                    "app": MESSAGING_PROXY_APP,
                    "allocation_type": "Derived",
                },
            },
            "screen_time_residual": {
                "category": (
                    DERIVED_SCREEN_TIME_CATEGORY
                ),
                "subcategory": (
                    DERIVED_SCREEN_TIME_SUBCATEGORY
                ),
                "allocation_type": "Derived",
                "positive_residual_only": True,
                "negative_difference": (
                    "Preserve as Apple reconciliation "
                    "anomaly without creating additional "
                    "time."
                ),
            },
        },
    }

    output = metadata_path(
        target_date
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def process_date(
    target_date: str,
    force: bool,
) -> BuildResult:
    """Build outputs for one date."""
    extraction_path = canonical_path(
        target_date
    )

    if not extraction_path.exists():
        raise FileNotFoundError(
            f"Missing canonical extraction: "
            f"{extraction_path}"
        )

    extraction = load_json(
        extraction_path
    )

    if extraction.get("status") != "canonical":
        raise ValueError(
            "Extraction is not canonical."
        )

    if extraction.get("date") != target_date:
        raise ValueError(
            "Extraction date does not match "
            f"{target_date}."
        )

    headline = calculate_headline_total(
        extraction
    )

    category_total = calculate_category_total(
        extraction
    )

    fact_rows = build_fact_rows(
        extraction
    )

    analytical_total = validate_fact_rows(
        extraction,
        fact_rows,
    )

    daily_rows = build_daily_rows(
        fact_rows
    )

    daily_total = sum(
        int(row["Duration_sec"])
        for row in daily_rows
    )

    if daily_total != analytical_total:
        raise ValueError(
            "Daily rows do not reconcile to analytical "
            f"Screen Time total: "
            f"{daily_total} != "
            f"{analytical_total}."
        )

    fact_file = fact_path(
        target_date
    )

    daily_file = daily_path(
        target_date
    )

    fact_status = write_if_changed(
        fact_file,
        serialize_csv(
            fact_rows,
            FACT_COLUMNS,
        ),
        force,
    )

    daily_status = write_if_changed(
        daily_file,
        serialize_csv(
            daily_rows,
            DAILY_COLUMNS,
        ),
        force,
    )

    write_metadata(
        target_date=target_date,
        extraction_path=extraction_path,
        fact_file=fact_file,
        daily_file=daily_file,
        fact_rows=fact_rows,
        daily_rows=daily_rows,
    )

    if (
        fact_status == STATUS_CHANGED
        or daily_status == STATUS_CHANGED
    ):
        status = STATUS_CHANGED
    elif (
        fact_status == STATUS_NEW
        or daily_status == STATUS_NEW
    ):
        status = STATUS_NEW
    else:
        status = STATUS_UNCHANGED

    return BuildResult(
        date=target_date,
        status=status,
        fact_path=fact_file,
        daily_path=daily_file,
        row_count=len(fact_rows),
        total_seconds=daily_total,
        headline_seconds=headline,
        category_total_seconds=category_total,
        reconciliation_difference_seconds=(
            headline - category_total
        ),
    )


def print_reconciliation(
    result: BuildResult,
) -> None:
    """Print reconciliation information for one date."""
    difference = (
        result.reconciliation_difference_seconds
    )

    if difference > 0:
        minutes, seconds = divmod(
            difference,
            60,
        )

        print(
            "  Reconciliation: "
            "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES"
        )
        print(
            "  Unresolved: "
            f"{minutes}m {seconds}s"
        )

    elif difference < 0:
        excess = abs(difference)
        minutes, seconds = divmod(
            excess,
            60,
        )

        print(
            "  Reconciliation: "
            "VISIBLE_CATEGORIES_EXCEED_HEADLINE"
        )
        print(
            "  Apple anomaly: "
            f"visible categories exceed headline by "
            f"{minutes}m {seconds}s; "
            "preserved without creating additional time."
        )

    else:
        print(
            "  Reconciliation: RECONCILED"
        )


def main() -> int:
    """Run the iPhone Screen Time builder."""
    args = parse_arguments()

    print(
        "# iPhone Screen Time Builder"
    )
    print()
    print(
        f"Month : {args.month}"
    )
    print(
        "Dates : "
        + (
            ", ".join(args.date)
            if args.date
            else "all canonical dates"
        )
    )
    print(
        f"Force : {args.force}"
    )
    print(
        "API   : 0 calls"
    )
    print(
        "Cost  : $0.000000"
    )

    try:
        dates = discover_dates(
            args.month,
            args.date,
        )
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}"
        )
        return 1

    if not dates:
        print()
        print(
            "RESULT: NO CANONICAL DATES FOUND."
        )
        return 1

    counts = {
        STATUS_NEW: 0,
        STATUS_UNCHANGED: 0,
        STATUS_CHANGED: 0,
        STATUS_FAILED: 0,
    }

    total_rows = 0
    total_seconds = 0

    for target_date in dates:
        try:
            result = process_date(
                target_date,
                args.force,
            )

            counts[result.status] += 1
            total_rows += result.row_count
            total_seconds += result.total_seconds

            print()
            print(
                f"{target_date} | "
                f"{result.status} | "
                f"{result.row_count} Fact rows | "
                f"{result.total_seconds}s"
            )

            print(
                f"  Fact : {result.fact_path}"
            )

            print(
                f"  Daily: {result.daily_path}"
            )

            print_reconciliation(
                result
            )

        except Exception as exc:
            counts[STATUS_FAILED] += 1

            print(
                f"{target_date} | FAILED | "
                f"{type(exc).__name__}: {exc}"
            )

    print()
    print(
        "=== IPHONE SCREEN TIME BUILD SUMMARY ==="
    )

    print(
        f"NEW         : {counts[STATUS_NEW]}"
    )
    print(
        f"UNCHANGED   : {counts[STATUS_UNCHANGED]}"
    )
    print(
        f"CHANGED     : {counts[STATUS_CHANGED]}"
    )
    print(
        f"FAILED      : {counts[STATUS_FAILED]}"
    )
    print(
        f"Fact rows   : {total_rows}"
    )
    print(
        f"Allocated   : {total_seconds / 3600:.4f}h"
    )
    print(
        "API calls   : 0"
    )
    print(
        "Cost        : $0.000000"
    )

    if counts[STATUS_FAILED]:
        print()
        print(
            "RESULT: IPHONE SCREEN TIME BUILD FAILED."
        )
        return 1

    print()
    print(
        "RESULT: IPHONE SCREEN TIME BUILD PASSED."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())