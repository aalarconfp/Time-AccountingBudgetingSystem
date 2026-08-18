# iphone_screen_time_promote.py

"""Promote reviewed Apple Screen Time candidates to canonical data.

This operation is local and costs $0.

Before promotion, existing canonical extraction and metadata files are
copied into a dated backup directory.

Reconciliation rules:

    HEADLINE_EXCEEDS_VISIBLE_CATEGORIES
        headline > visible categories
        unresolved = headline - visible categories

    MATCH
        headline == visible categories
        unresolved = 0

    VISIBLE_CATEGORIES_EXCEED_HEADLINE
        visible categories > headline
        unresolved = 0
        signed reconciliation difference is preserved as an anomaly

The final case must not be converted into additional time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
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

CANDIDATE_EXTRACTION = "AI_Extraction_Candidate.json"
CANDIDATE_METADATA = "AI_Metadata_Candidate.json"

CANONICAL_EXTRACTION = "AI_Extraction.json"
CANONICAL_METADATA = "AI_Metadata.json"

VALID_RECONCILIATION_STATUSES = {
    "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES",
    "MATCH",
    "VISIBLE_CATEGORIES_EXCEED_HEADLINE",
}


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Promote reviewed iPhone Screen Time "
            "candidates to canonical data."
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
            "Date to promote in YYYY-MM-DD format. "
            "May be specified multiple times."
        ),
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
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


def sha256(path: Path) -> str:
    """Calculate a file SHA-256 hash."""
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def validate_candidate(
    candidate: dict[str, Any],
    expected_date: str,
) -> None:
    """Validate a candidate before promotion."""
    if candidate.get("date") != expected_date:
        raise ValueError(
            "Candidate date does not match "
            f"requested date: "
            f"{candidate.get('date')} != "
            f"{expected_date}"
        )

    total = int(
        candidate.get(
            "total_screen_time_sec",
            -1,
        )
    )

    category_total = int(
        candidate.get(
            "category_total_sec",
            -1,
        )
    )

    unresolved = int(
        candidate.get(
            "unresolved_screen_time_sec",
            -1,
        )
    )

    if total < 0:
        raise ValueError(
            "Invalid total_screen_time_sec."
        )

    if category_total < 0:
        raise ValueError(
            "Invalid category_total_sec."
        )

    if unresolved < 0:
        raise ValueError(
            "Invalid unresolved_screen_time_sec."
        )

    reconciliation_status = candidate.get(
        "reconciliation_status"
    )

    if reconciliation_status not in (
        VALID_RECONCILIATION_STATUSES
    ):
        raise ValueError(
            "Invalid reconciliation_status: "
            f"{reconciliation_status!r}"
        )

    rebuild = candidate.get(
        "rebuild",
        {},
    )

    if rebuild.get(
        "method"
    ) != "deterministic_local_rebuild":
        raise ValueError(
            "Candidate was not produced by "
            "the deterministic local rebuild."
        )

    reconciliation_difference = candidate.get(
        "reconciliation_difference_sec"
    )

    if reconciliation_difference is not None:
        reconciliation_difference = int(
            reconciliation_difference
        )

    if (
        reconciliation_status
        == "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES"
    ):
        expected_difference = (
            total - category_total
        )

        if expected_difference <= 0:
            raise ValueError(
                "Invalid HEADLINE_EXCEEDS_VISIBLE_CATEGORIES "
                "candidate: headline is not greater than "
                "visible categories."
            )

        if unresolved != expected_difference:
            raise ValueError(
                "Headline reconciliation failed: "
                f"{total} != "
                f"{category_total} + "
                f"{unresolved}"
            )

        if (
            reconciliation_difference is not None
            and reconciliation_difference
            != expected_difference
        ):
            raise ValueError(
                "Invalid reconciliation difference: "
                f"{reconciliation_difference} != "
                f"{expected_difference}"
            )

        return

    if reconciliation_status == "MATCH":
        if total != category_total:
            raise ValueError(
                "Invalid MATCH candidate: "
                f"{total} != {category_total}"
            )

        if unresolved != 0:
            raise ValueError(
                "Invalid MATCH candidate: "
                "unresolved time must be 0."
            )

        if (
            reconciliation_difference is not None
            and reconciliation_difference != 0
        ):
            raise ValueError(
                "Invalid reconciliation difference: "
                f"{reconciliation_difference} != 0"
            )

        return

    if reconciliation_status == (
        "VISIBLE_CATEGORIES_EXCEED_HEADLINE"
    ):
        expected_difference = (
            total - category_total
        )

        if expected_difference >= 0:
            raise ValueError(
                "Invalid VISIBLE_CATEGORIES_EXCEED_HEADLINE "
                "candidate: visible categories do not "
                "exceed the headline."
            )

        if unresolved != 0:
            raise ValueError(
                "Invalid VISIBLE_CATEGORIES_EXCEED_HEADLINE "
                "candidate: unresolved time must remain 0."
            )

        if (
            reconciliation_difference is not None
            and reconciliation_difference
            != expected_difference
        ):
            raise ValueError(
                "Invalid reconciliation difference: "
                f"{reconciliation_difference} != "
                f"{expected_difference}"
            )

        return


def create_backup(
    directory: Path,
    canonical_extraction: Path,
    canonical_metadata: Path,
) -> Path:
    """Create a timestamped backup of existing canonical files."""
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_directory = (
        directory
        / "backup"
        / timestamp
    )

    backup_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    if canonical_extraction.exists():
        shutil.copy2(
            canonical_extraction,
            backup_directory
            / CANONICAL_EXTRACTION,
        )

    if canonical_metadata.exists():
        shutil.copy2(
            canonical_metadata,
            backup_directory
            / CANONICAL_METADATA,
        )

    return backup_directory


def promote_date(
    target_date: str,
) -> None:
    """Promote one reviewed candidate to canonical."""
    directory = (
        RAW_OUTPUT
        / target_date[:7]
        / target_date
    )

    candidate_extraction = (
        directory
        / CANDIDATE_EXTRACTION
    )

    candidate_metadata = (
        directory
        / CANDIDATE_METADATA
    )

    canonical_extraction = (
        directory
        / CANONICAL_EXTRACTION
    )

    canonical_metadata = (
        directory
        / CANONICAL_METADATA
    )

    if not candidate_extraction.exists():
        raise FileNotFoundError(
            f"Missing candidate: "
            f"{candidate_extraction}"
        )

    candidate = load_json(
        candidate_extraction
    )

    validate_candidate(
        candidate,
        target_date,
    )

    backup_directory = create_backup(
        directory,
        canonical_extraction,
        canonical_metadata,
    )

    now = datetime.now()

    promoted_extraction = dict(
        candidate
    )

    promoted_extraction[
        "status"
    ] = "canonical"

    promoted_extraction[
        "canonicalized_at"
    ] = now.isoformat(
        timespec="seconds"
    )

    promoted_extraction[
        "canonical_source"
    ] = CANDIDATE_EXTRACTION

    save_json(
        canonical_extraction,
        promoted_extraction,
    )

    if candidate_metadata.exists():
        metadata = load_json(
            candidate_metadata
        )
    else:
        metadata = {
            "date": target_date,
        }

    metadata[
        "status"
    ] = "canonical"

    metadata[
        "content_hash"
    ] = sha256(
        canonical_extraction
    )

    metadata[
        "canonicalized_at"
    ] = now.isoformat(
        timespec="seconds"
    )

    metadata[
        "canonical_source"
    ] = CANDIDATE_EXTRACTION

    save_json(
        canonical_metadata,
        metadata,
    )

    reconciliation_status = candidate.get(
        "reconciliation_status"
    )

    print(
        f"{target_date} | PROMOTED | "
        "0 API calls | $0.000000"
    )

    print(
        f"  Canonical: "
        f"{canonical_extraction}"
    )

    print(
        f"  Backup   : "
        f"{backup_directory}"
    )

    print(
        f"  Total    : "
        f"{candidate['total_screen_time_display']}"
    )

    print(
        f"  Categories: "
        f"{candidate['category_total_display']}"
    )

    print(
        f"  Unresolved: "
        f"{candidate['unresolved_screen_time_display']}"
    )

    print(
        f"  Reconciliation: "
        f"{reconciliation_status}"
    )

    if (
        reconciliation_status
        == "VISIBLE_CATEGORIES_EXCEED_HEADLINE"
    ):
        difference = (
            int(
                candidate[
                    "category_total_sec"
                ]
            )
            - int(
                candidate[
                    "total_screen_time_sec"
                ]
            )
        )

        print(
            "  Apple anomaly: visible categories "
            "exceed headline by "
            f"{difference}s; preserved without "
            "creating additional time."
        )


def main() -> int:
    """Promote reviewed candidates."""
    args = parse_arguments()

    print(
        "# iPhone Screen Time Candidate Promotion"
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

    promoted = 0
    failed = 0

    for target_date in args.date:
        try:
            if not target_date.startswith(
                f"{args.month}-"
            ):
                raise ValueError(
                    f"{target_date} is outside "
                    f"{args.month}."
                )

            promote_date(
                target_date
            )

            promoted += 1

        except Exception as exc:
            failed += 1

            print(
                f"{target_date} | FAILED | "
                f"{type(exc).__name__}: {exc}"
            )

    print()
    print(
        "=== PROMOTION SUMMARY ==="
    )

    print(
        f"Promoted : {promoted}"
    )

    print(
        f"Failed   : {failed}"
    )

    print(
        "API calls: 0"
    )

    print(
        "Cost     : $0.000000"
    )

    if failed:
        print()
        print(
            "RESULT: PROMOTION FAILED."
        )
        return 1

    print()
    print(
        "RESULT: CANDIDATES PROMOTED "
        "TO CANONICAL."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )