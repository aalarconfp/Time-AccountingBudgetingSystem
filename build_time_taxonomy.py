# G:\My Drive\Personal Life\Habit and Wellness\System_Tracker\build_time_taxonomy.py

"""Validate the canonical Category / Domain / Energy / Goal mapping layer."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CATEGORIES = {
    "Social Networking",
    "Games",
    "Entertainment",
    "Creativity",
    "Productivity & Finance",
    "Information & Reading",
    "Education",
    "Health & Fitness",
    "Utilities",
    "Shopping & Food",
    "Travel",
    "News",
}

DOMAINS = {
    "Vocational",
    "Intellectual",
    "Economical",
    "Relational",
    "Physical",
    "Recreational",
    "Spiritual",
}

ENERGIES = {
    "Deep",
    "Shallow",
    "Active",
    "Passive",
    "Recovery",
}

GOALS = {
    "Investment",
    "Maintenance",
    "Consumption",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file."""
    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        return list(csv.DictReader(handle))


def validate(output: Path) -> list[str]:
    """Validate all taxonomy lookup files."""
    errors: list[str] = []

    defaults = read_csv(
        output / "Dim_Category_Default.csv"
    )
    activities = read_csv(
        output / "Dim_Activity.csv"
    )

    seen_categories: set[str] = set()

    for row in defaults:
        category = row["Canonical_Category"]

        if category in seen_categories:
            errors.append(
                f"Duplicate category default: {category}"
            )

        seen_categories.add(category)

        if category not in CATEGORIES:
            errors.append(
                f"Unknown category: {category}"
            )

        if row["Domain"] not in DOMAINS:
            errors.append(
                f"Invalid domain: "
                f"{category} -> {row['Domain']}"
            )

        if row["Energy"] not in ENERGIES:
            errors.append(
                f"Invalid energy: "
                f"{category} -> {row['Energy']}"
            )

        if row["Goal"] not in GOALS:
            errors.append(
                f"Invalid goal: "
                f"{category} -> {row['Goal']}"
            )

    missing_categories = CATEGORIES - seen_categories

    errors.extend(
        f"Missing category default: {category}"
        for category in sorted(missing_categories)
    )

    seen_activities: set[tuple[str, str]] = set()

    for row in activities:
        key = (
            row["Source"],
            row["Activity_Name"],
        )

        if key in seen_activities:
            errors.append(
                f"Duplicate activity: "
                f"{key[0]} / {key[1]}"
            )

        seen_activities.add(key)

        category = row["Canonical_Category"]

        if category not in CATEGORIES:
            errors.append(
                f"Unknown activity category: {key}"
            )

        if row["Mapping_Type"] == "Excluded":
            if any(
                row[field]
                for field in (
                    "Domain",
                    "Energy",
                    "Goal",
                )
            ):
                errors.append(
                    f"Excluded activity has dimensions: {key}"
                )

            continue

        for field, allowed_values in (
            ("Domain", DOMAINS),
            ("Energy", ENERGIES),
            ("Goal", GOALS),
        ):
            if row[field] not in allowed_values:
                errors.append(
                    f"Invalid {field}: "
                    f"{key} -> {row[field]}"
                )

    return errors


def main() -> int:
    """Validate the generated taxonomy."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate the canonical time taxonomy."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "output/Reference/Taxonomy"
        ),
    )

    args = parser.parse_args()
    output = args.output.resolve()

    errors = validate(output)

    if errors:
        print(
            "TIME TAXONOMY VALIDATION FAILED"
        )

        for error in errors:
            print(f"ERROR: {error}")

        return 1

    print(
        "TIME TAXONOMY VALIDATION PASSED"
    )

    print(
        "Categories : "
        f"{len(read_csv(output / 'Dim_Category_Default.csv'))}"
    )

    print(
        "Activities : "
        f"{len(read_csv(output / 'Dim_Activity.csv'))}"
    )

    print("Domains    : 7")
    print("Energies   : 5")
    print("Goals      : 3")
    print(f"Output     : {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())