# iphone_screen_time_categorize_unresolved.py

"""Categorize Apple Screen Time reconciliation time as Utilities.

Positive reconciliation residuals are assigned to the project's
Utilities / Screen Time / System category.

When visible Apple categories exceed the Apple headline Screen Time,
the negative difference is preserved as an Apple reconciliation anomaly
and is not allocated to any analytical category.

This is a zero-cost local migration.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
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

TARGET_CATEGORY = "Utilities"
TARGET_SUBCATEGORY = "Screen Time / System"


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Categorize positive Apple Screen Time "
            "reconciliation residuals as Utilities."
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
        required=True,
        help=(
            "Date in YYYY-MM-DD format. "
            "Can be specified multiple times."
        ),
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON from disk."""
    return json.loads(
        path.read_text(encoding="utf-8")
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


def get_reconciliation_values(
    extraction: dict[str, Any],
) -> tuple[int, int, int, int]:
    """Return headline, categories, stored unresolved, and difference."""
    total = int(
        extraction["total_screen_time_sec"]
    )

    category_total = int(
        extraction["category_total_sec"]
    )

    unresolved = int(
        extraction["unresolved_screen_time_sec"]
    )

    difference = total - category_total

    return (
        total,
        category_total,
        unresolved,
        difference,
    )


def validate_extraction(
    extraction: dict[str, Any],
    target_date: str,
) -> tuple[int, int, int, int]:
    """Validate canonical extraction reconciliation."""
    if extraction.get("date") != target_date:
        raise ValueError(
            "Extraction date does not match "
            f"{target_date}."
        )

    if extraction.get("status") != "canonical":
        raise ValueError(
            "Only canonical extractions may be "
            "modified."
        )

    required_fields = (
        "total_screen_time_sec",
        "category_total_sec",
        "unresolved_screen_time_sec",
    )

    for field in required_fields:
        if field not in extraction:
            raise ValueError(
                f"Missing required field: {field}"
            )

    (
        total,
        category_total,
        unresolved,
        difference,
    ) = get_reconciliation_values(
        extraction
    )

    expected_unresolved = max(
        difference,
        0,
    )

    if unresolved != expected_unresolved:
        raise ValueError(
            "Screen Time reconciliation failed: "
            f"{total} != "
            f"{category_total} + "
            f"{expected_unresolved}; "
            f"stored unresolved={unresolved}"
        )

    return (
        total,
        category_total,
        unresolved,
        difference,
    )


def update_extraction(
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Assign positive unresolved Screen Time to Utilities."""
    updated = json.loads(
        json.dumps(extraction)
    )

    unresolved = int(
        updated[
            "unresolved_screen_time_sec"
        ]
    )

    if unresolved <= 0:
        return updated

    existing_category = updated.get(
        "unresolved_screen_time_category"
    )

    if existing_category not in (
        None,
        "Apple Screen Time Unresolved",
        TARGET_CATEGORY,
    ):
        raise ValueError(
            "Unexpected existing unresolved "
            f"category: {existing_category}"
        )

    updated[
        "unresolved_screen_time_category"
    ] = TARGET_CATEGORY

    updated[
        "unresolved_screen_time_subcategory"
    ] = TARGET_SUBCATEGORY

    updated[
        "unresolved_screen_time_allocation_type"
    ] = "Derived"

    updated[
        "unresolved_screen_time_classification"
    ] = {
        "category": TARGET_CATEGORY,
        "subcategory": TARGET_SUBCATEGORY,
        "allocation_type": "Derived",
        "basis": (
            "Local project classification of the "
            "positive difference between Apple "
            "headline Screen Time and visible Apple "
            "category totals."
        ),
    }

    updated[
        "classification"
    ] = {
        "unresolved_screen_time": {
            "category": TARGET_CATEGORY,
            "subcategory": TARGET_SUBCATEGORY,
            "duration_sec": unresolved,
            "allocation_type": "Derived",
        }
    }

    updated[
        "classification_updated_at"
    ] = datetime.now().isoformat(
        timespec="seconds"
    )

    updated[
        "classification_method"
    ] = "project_taxonomy_mapping"

    return updated


def process_date(
    target_date: str,
) -> str:
    """Process one canonical extraction."""
    directory = (
        RAW_OUTPUT
        / target_date[:7]
        / target_date
    )

    extraction_path = (
        directory
        / "AI_Extraction.json"
    )

    metadata_path = (
        directory
        / "AI_Metadata.json"
    )

    if not extraction_path.exists():
        raise FileNotFoundError(
            f"Missing canonical extraction: "
            f"{extraction_path}"
        )

    extraction = load_json(
        extraction_path
    )

    (
        total,
        category_total,
        unresolved,
        difference,
    ) = validate_extraction(
        extraction,
        target_date,
    )

    if difference < 0:
        print(
            f"{target_date} | ANOMALY PRESERVED | "
            f"categories exceed headline by "
            f"{abs(difference)}s"
        )
        print(
            "  No unresolved time allocated."
        )
        return "ANOMALY"

    if difference == 0:
        print(
            f"{target_date} | NO RESIDUAL | "
            f"{total}s fully reconciled"
        )
        return "UNCHANGED"

    updated = update_extraction(
        extraction
    )

    backup_directory = (
        directory
        / "backup"
        / (
            "before_utility_classification_"
            + datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )
        )
    )

    backup_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_extraction = (
        backup_directory
        / "AI_Extraction.json"
    )

    backup_extraction.write_bytes(
        extraction_path.read_bytes()
    )

    if metadata_path.exists():
        (
            backup_directory
            / "AI_Metadata.json"
        ).write_bytes(
            metadata_path.read_bytes()
        )

    save_json(
        extraction_path,
        updated,
    )

    if metadata_path.exists():
        metadata = load_json(
            metadata_path
        )

        metadata[
            "classification"
        ] = {
            "unresolved_screen_time": {
                "category": TARGET_CATEGORY,
                "subcategory": TARGET_SUBCATEGORY,
                "allocation_type": "Derived",
            }
        }

        metadata[
            "classification_updated_at"
        ] = datetime.now().isoformat(
            timespec="seconds"
        )

        save_json(
            metadata_path,
            metadata,
        )

    print(
        f"{target_date} | CLASSIFIED | "
        f"{unresolved}s -> "
        f"{TARGET_CATEGORY} / "
        f"{TARGET_SUBCATEGORY}"
    )

    print(
        f"  Backup: {backup_directory}"
    )

    return "CLASSIFIED"


def main() -> int:
    """Run the local classification migration."""
    args = parse_arguments()

    print(
        "# iPhone Screen Time "
        "Unresolved Classification"
    )
    print()
    print(
        f"Month : {args.month}"
    )
    print(
        f"Dates : {', '.join(args.date)}"
    )
    print(
        "API   : 0 calls"
    )
    print(
        "Cost  : $0.000000"
    )
    print()

    failed = 0
    classified = 0
    anomalies = 0
    unchanged = 0

    for target_date in args.date:
        try:
            if not target_date.startswith(
                f"{args.month}-"
            ):
                raise ValueError(
                    f"{target_date} is outside "
                    f"{args.month}."
                )

            result = process_date(
                target_date
            )

            if result == "CLASSIFIED":
                classified += 1
            elif result == "ANOMALY":
                anomalies += 1
            elif result == "UNCHANGED":
                unchanged += 1

        except Exception as exc:
            failed += 1

            print(
                f"{target_date} | FAILED | "
                f"{type(exc).__name__}: {exc}"
            )

    print()
    print(
        "=== CLASSIFICATION SUMMARY ==="
    )

    print(
        f"Classified: {classified}"
    )

    print(
        f"Anomalies : {anomalies}"
    )

    print(
        f"Unchanged : {unchanged}"
    )

    print(
        f"Failed    : {failed}"
    )

    print(
        "API calls : 0"
    )

    print(
        "Cost      : $0.000000"
    )

    if failed:
        print()
        print(
            "RESULT: CLASSIFICATION FAILED."
        )
        return 1

    print()
    print(
        "RESULT: UNRESOLVED SCREEN TIME "
        "CLASSIFICATION COMPLETED."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())