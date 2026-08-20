"""
System Tracker - Final Detail Analysis

Purpose
-------
Analyze the frozen final reconciliation output without modifying or
recalculating the reconciliation layer.

Hierarchy
---------
Device
Device -> Category
Device -> Category -> Subcategory
Device -> Category -> Subcategory -> Domain
Device -> Category -> Subcategory -> Domain -> Energy
Device -> Category -> Subcategory -> Domain -> Energy -> Goal

Category
Category -> Subcategory
Category -> Subcategory -> Domain
Category -> Subcategory -> Domain -> Energy
Category -> Subcategory -> Domain -> Energy -> Goal

Additional analytical views
----------------------------
- Device x Category
- Domain
- Energy
- Goal
- Daily analysis
- Off-Device Life
- Time-universe summary
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_FINAL_ROOT = (
    PROJECT_ROOT
    / "output"
    / "Integrated"
    / "Analysis"
    / "Final"
)

DATE_FORMAT = "%Y-%m-%d"
SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0

HIERARCHY_FIELDS = [
    "Analysis_Level",
    "Device",
    "Category",
    "Subcategory",
    "Domain",
    "Energy",
    "Goal",
    "Duration_sec",
    "Duration_min",
    "Percent_of_Total",
]

DAILY_FIELDS = [
    "Date",
    "Device",
    "Category",
    "Subcategory",
    "Domain",
    "Energy",
    "Goal",
    "Duration_sec",
    "Duration_min",
    "Percent_of_Day",
]

SUMMARY_FIELDS = [
    "Analysis_Level",
    "Dimension",
    "Value",
    "Duration_sec",
    "Duration_min",
    "Percent_of_Total",
]


@dataclass(frozen=True)
class FinalRecord:
    date: str
    device: str
    source: str
    category: str
    subcategory: str
    domain: str
    energy: str
    goal: str
    duration_sec: float

    @property
    def duration_min(self) -> float:
        return self.duration_sec / SECONDS_PER_MINUTE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build detailed analysis from frozen final reconciliation."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--final-root",
        default=str(DEFAULT_FINAL_ROOT),
        help="Root directory containing the frozen final-analysis outputs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing detail-analysis outputs.",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), DATE_FORMAT).date()


def normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_float(value: object) -> float:
    text = normalize(value)
    if not text:
        return 0.0

    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc


def format_duration(seconds: float) -> str:
    total_minutes = int(round(seconds / SECONDS_PER_MINUTE))
    hours, minutes = divmod(total_minutes, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m"


def find_final_csv(
    output_dir: Path,
    start_date: date,
    end_date: date,
) -> Path:
    expected_name = (
        f"Final_Analysis_{start_date.isoformat()}_"
        f"{end_date.isoformat()}.csv"
    )
    expected_path = output_dir / expected_name

    if expected_path.exists():
        return expected_path

    candidates = sorted(output_dir.glob("Final_Analysis_*.csv"))

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise FileNotFoundError(
            f"No frozen final-analysis CSV found in {output_dir}"
        )

    raise FileNotFoundError(
        "Unable to determine the frozen final-analysis CSV. "
        f"Expected {expected_path}."
    )


def resolve_duration_column(fieldnames: Sequence[str]) -> str:
    preferred = [
        "Duration_sec",
        "Duration_seconds",
        "Duration",
    ]

    for field in preferred:
        if field in fieldnames:
            return field

    raise ValueError(
        "Final analysis CSV does not contain a supported duration column. "
        f"Available columns: {list(fieldnames)}"
    )


def resolve_field(
    fieldnames: Sequence[str],
    candidates: Sequence[str],
    default: str = "",
) -> str:
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate

    return default


def load_final_records(
    path: Path,
    start_date: date,
    end_date: date,
) -> list[FinalRecord]:
    records: list[FinalRecord] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        fieldnames = reader.fieldnames

        date_field = resolve_field(
            fieldnames,
            ["Date", "date"],
        )
        if not date_field:
            raise ValueError("Final analysis CSV has no Date column.")

        device_field = resolve_field(
            fieldnames,
            ["Device", "device"],
        )

        source_field = resolve_field(
            fieldnames,
            ["Source", "source"],
        )

        category_field = resolve_field(
            fieldnames,
            ["Category", "category"],
        )

        subcategory_field = resolve_field(
            fieldnames,
            ["Subcategory", "subcategory"],
        )

        domain_field = resolve_field(
            fieldnames,
            ["Domain", "domain"],
        )

        energy_field = resolve_field(
            fieldnames,
            ["Energy", "energy"],
        )

        goal_field = resolve_field(
            fieldnames,
            ["Goal", "goal"],
        )

        duration_field = resolve_duration_column(fieldnames)

        for row_number, row in enumerate(reader, start=2):
            raw_date = normalize(row.get(date_field))

            if not raw_date:
                continue

            try:
                row_date = parse_date(raw_date)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid date at {path}:{row_number}: {raw_date!r}"
                ) from exc

            if not start_date <= row_date <= end_date:
                continue

            duration_sec = parse_float(row.get(duration_field))

            if duration_sec <= 0:
                continue

            device = normalize(row.get(device_field))
            source = normalize(row.get(source_field))
            category = normalize(row.get(category_field))
            subcategory = normalize(row.get(subcategory_field))
            domain = normalize(row.get(domain_field))
            energy = normalize(row.get(energy_field))
            goal = normalize(row.get(goal_field))

            if not device:
                device = source or "Unknown"

            records.append(
                FinalRecord(
                    date=row_date.isoformat(),
                    device=device,
                    source=source,
                    category=category or "Uncategorized",
                    subcategory=subcategory,
                    domain=domain,
                    energy=energy,
                    goal=goal,
                    duration_sec=duration_sec,
                )
            )

    if not records:
        raise ValueError(
            f"No final analytical records found for "
            f"{start_date.isoformat()} -> {end_date.isoformat()}."
        )

    return records


def aggregate(
    records: Iterable[FinalRecord],
    fields: Sequence[str],
) -> dict[tuple[str, ...], float]:
    totals: dict[tuple[str, ...], float] = defaultdict(float)

    for record in records:
        values = {
            "Date": record.date,
            "Device": record.device,
            "Category": record.category,
            "Subcategory": record.subcategory,
            "Domain": record.domain,
            "Energy": record.energy,
            "Goal": record.goal,
        }

        key = tuple(values[field] for field in fields)
        totals[key] += record.duration_sec

    return dict(totals)


def hierarchy_rows(
    records: Sequence[FinalRecord],
) -> list[dict[str, object]]:
    hierarchy_levels: list[tuple[str, tuple[str, ...]]] = [
        ("Device", ("Device",)),
        ("Device → Category", ("Device", "Category")),
        (
            "Device → Category → Subcategory",
            ("Device", "Category", "Subcategory"),
        ),
        (
            "Device → Category → Subcategory → Domain",
            ("Device", "Category", "Subcategory", "Domain"),
        ),
        (
            "Device → Category → Subcategory → Domain → Energy",
            (
                "Device",
                "Category",
                "Subcategory",
                "Domain",
                "Energy",
            ),
        ),
        (
            "Device → Category → Subcategory → Domain → Energy → Goal",
            (
                "Device",
                "Category",
                "Subcategory",
                "Domain",
                "Energy",
                "Goal",
            ),
        ),
        ("Category", ("Category",)),
        (
            "Category → Subcategory",
            ("Category", "Subcategory"),
        ),
        (
            "Category → Subcategory → Domain",
            ("Category", "Subcategory", "Domain"),
        ),
        (
            "Category → Subcategory → Domain → Energy",
            ("Category", "Subcategory", "Domain", "Energy"),
        ),
        (
            "Category → Subcategory → Domain → Energy → Goal",
            (
                "Category",
                "Subcategory",
                "Domain",
                "Energy",
                "Goal",
            ),
        ),
    ]

    total_seconds = sum(record.duration_sec for record in records)

    rows: list[dict[str, object]] = []

    for level_name, fields in hierarchy_levels:
        totals = aggregate(records, fields)

        for key, duration_sec in sorted(
            totals.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            values = dict(zip(fields, key))

            rows.append(
                {
                    "Analysis_Level": level_name,
                    "Device": values.get("Device", ""),
                    "Category": values.get("Category", ""),
                    "Subcategory": values.get("Subcategory", ""),
                    "Domain": values.get("Domain", ""),
                    "Energy": values.get("Energy", ""),
                    "Goal": values.get("Goal", ""),
                    "Duration_sec": round(duration_sec, 3),
                    "Duration_min": round(
                        duration_sec / SECONDS_PER_MINUTE,
                        3,
                    ),
                    "Percent_of_Total": round(
                        (
                            duration_sec / total_seconds * 100.0
                            if total_seconds > 0
                            else 0.0
                        ),
                        3,
                    ),
                }
            )

    return rows


def summary_rows(
    records: Sequence[FinalRecord],
) -> list[dict[str, object]]:
    total_seconds = sum(record.duration_sec for record in records)

    dimensions = [
        ("Device", ("Device",)),
        ("Category", ("Category",)),
        ("Domain", ("Domain",)),
        ("Energy", ("Energy",)),
        ("Goal", ("Goal",)),
    ]

    rows: list[dict[str, object]] = []

    for dimension, fields in dimensions:
        totals = aggregate(records, fields)

        for key, duration_sec in sorted(
            totals.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            value = key[0]

            rows.append(
                {
                    "Analysis_Level": dimension,
                    "Dimension": dimension,
                    "Value": value,
                    "Duration_sec": round(duration_sec, 3),
                    "Duration_min": round(
                        duration_sec / SECONDS_PER_MINUTE,
                        3,
                    ),
                    "Percent_of_Total": round(
                        (
                            duration_sec / total_seconds * 100.0
                            if total_seconds > 0
                            else 0.0
                        ),
                        3,
                    ),
                }
            )

    return rows


def device_category_rows(
    records: Sequence[FinalRecord],
) -> list[dict[str, object]]:
    totals = aggregate(
        records,
        ("Device", "Category"),
    )

    total_seconds = sum(record.duration_sec for record in records)

    rows: list[dict[str, object]] = []

    for (device, category), duration_sec in sorted(
        totals.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        rows.append(
            {
                "Device": device,
                "Category": category,
                "Duration_sec": round(duration_sec, 3),
                "Duration_min": round(
                    duration_sec / SECONDS_PER_MINUTE,
                    3,
                ),
                "Percent_of_Total": round(
                    duration_sec / total_seconds * 100.0
                    if total_seconds > 0
                    else 0.0,
                    3,
                ),
            }
        )

    return rows


def daily_rows(
    records: Sequence[FinalRecord],
) -> list[dict[str, object]]:
    grouped = aggregate(
        records,
        (
            "Date",
            "Device",
            "Category",
            "Subcategory",
            "Domain",
            "Energy",
            "Goal",
        ),
    )

    daily_totals: dict[str, float] = defaultdict(float)

    for key, duration_sec in grouped.items():
        daily_totals[key[0]] += duration_sec

    rows: list[dict[str, object]] = []

    for key, duration_sec in sorted(
        grouped.items(),
        key=lambda item: (
            item[0][0],
            -item[1],
            item[0][1:],
        ),
    ):
        (
            row_date,
            device,
            category,
            subcategory,
            domain,
            energy,
            goal,
        ) = key

        day_total = daily_totals[row_date]

        rows.append(
            {
                "Date": row_date,
                "Device": device,
                "Category": category,
                "Subcategory": subcategory,
                "Domain": domain,
                "Energy": energy,
                "Goal": goal,
                "Duration_sec": round(duration_sec, 3),
                "Duration_min": round(
                    duration_sec / SECONDS_PER_MINUTE,
                    3,
                ),
                "Percent_of_Day": round(
                    duration_sec / day_total * 100.0
                    if day_total > 0
                    else 0.0,
                    3,
                ),
            }
        )

    return rows


def off_device_rows(
    records: Sequence[FinalRecord],
) -> list[dict[str, object]]:
    return [
        row
        for row in hierarchy_rows(records)
        if row["Device"] == "Off-Device"
        and row["Category"] == "Off-Device Life"
    ]


def write_csv(
    path: Path,
    rows: Sequence[dict[str, object]],
    fieldnames: Sequence[str],
    force: bool,
) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"Output already exists: {path}. Use --force to overwrite."
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def build_report(
    records: Sequence[FinalRecord],
    start_date: date,
    end_date: date,
    hierarchy: Sequence[dict[str, object]],
    summaries: Sequence[dict[str, object]],
    device_category: Sequence[dict[str, object]],
) -> str:
    total_sec = sum(record.duration_sec for record in records)

    device_totals = {
        row["Value"]: float(row["Duration_sec"])
        for row in summaries
        if row["Analysis_Level"] == "Device"
    }

    category_totals = {
        row["Value"]: float(row["Duration_sec"])
        for row in summaries
        if row["Analysis_Level"] == "Category"
    }

    domain_totals = {
        row["Value"]: float(row["Duration_sec"])
        for row in summaries
        if row["Analysis_Level"] == "Domain"
    }

    energy_totals = {
        row["Value"]: float(row["Duration_sec"])
        for row in summaries
        if row["Analysis_Level"] == "Energy"
    }

    goal_totals = {
        row["Value"]: float(row["Duration_sec"])
        for row in summaries
        if row["Analysis_Level"] == "Goal"
    }

    lines = [
        "=== FINAL DETAIL ANALYSIS ===",
        "",
        f"Dates          : {start_date.isoformat()} -> "
        f"{end_date.isoformat()}",
        f"Final records  : {len(records)}",
        f"Final duration : {format_duration(total_sec)}",
        "",
        "=== DEVICE ===",
    ]

    for name, seconds in sorted(
        device_totals.items(),
        key=lambda item: -item[1],
    ):
        percentage = (
            seconds / total_sec * 100.0
            if total_sec > 0
            else 0.0
        )
        lines.append(
            f"{name:25s} "
            f"{format_duration(seconds):>10s} "
            f"{percentage:6.2f}%"
        )

    lines.extend(
        [
            "",
            "=== CATEGORY ===",
        ]
    )

    for name, seconds in sorted(
        category_totals.items(),
        key=lambda item: -item[1],
    ):
        percentage = (
            seconds / total_sec * 100.0
            if total_sec > 0
            else 0.0
        )
        lines.append(
            f"{name:30s} "
            f"{format_duration(seconds):>10s} "
            f"{percentage:6.2f}%"
        )

    lines.extend(
        [
            "",
            "=== DOMAIN ===",
        ]
    )

    for name, seconds in sorted(
        domain_totals.items(),
        key=lambda item: -item[1],
    ):
        percentage = (
            seconds / total_sec * 100.0
            if total_sec > 0
            else 0.0
        )
        lines.append(
            f"{name:25s} "
            f"{format_duration(seconds):>10s} "
            f"{percentage:6.2f}%"
        )

    lines.extend(
        [
            "",
            "=== ENERGY ===",
        ]
    )

    for name, seconds in sorted(
        energy_totals.items(),
        key=lambda item: -item[1],
    ):
        percentage = (
            seconds / total_sec * 100.0
            if total_sec > 0
            else 0.0
        )
        lines.append(
            f"{name:25s} "
            f"{format_duration(seconds):>10s} "
            f"{percentage:6.2f}%"
        )

    lines.extend(
        [
            "",
            "=== GOAL ===",
        ]
    )

    for name, seconds in sorted(
        goal_totals.items(),
        key=lambda item: -item[1],
    ):
        percentage = (
            seconds / total_sec * 100.0
            if total_sec > 0
            else 0.0
        )
        lines.append(
            f"{name:25s} "
            f"{format_duration(seconds):>10s} "
            f"{percentage:6.2f}%"
        )

    off_device_seconds = sum(
        record.duration_sec
        for record in records
        if record.device == "Off-Device"
        and record.category == "Off-Device Life"
    )

    lines.extend(
        [
            "",
            "=== OFF-DEVICE LIFE ===",
            f"Off-device life: {format_duration(off_device_seconds)}",
            (
                f"Share of analytical output: "
                f"{off_device_seconds / total_sec * 100.0:.2f}%"
                if total_sec > 0
                else "Share of analytical output: 0.00%"
            ),
            "",
            "=== OUTPUT COUNTS ===",
            f"Hierarchy rows       : {len(hierarchy)}",
            f"Device/category rows : {len(device_category)}",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if end_date < start_date:
        raise ValueError("End date cannot be before start date.")

    final_root = Path(args.final_root).resolve()

    period_dir = (
        final_root
        / f"{start_date.isoformat()}_{end_date.isoformat()}"
    )

    final_csv = find_final_csv(
        period_dir,
        start_date,
        end_date,
    )

    print("=== Final Detail Analysis ===")
    print(
        f"Dates : {start_date.isoformat()} -> "
        f"{end_date.isoformat()}"
    )
    print(f"Input : {final_csv}")

    records = load_final_records(
        final_csv,
        start_date,
        end_date,
    )

    print(f"Final records : {len(records)}")

    total_seconds = sum(
        record.duration_sec
        for record in records
    )

    print(f"Final duration: {format_duration(total_seconds)}")

    hierarchy = hierarchy_rows(records)
    summaries = summary_rows(records)
    device_category = device_category_rows(records)
    daily = daily_rows(records)

    off_device = off_device_rows(records)

    output_prefix = (
        f"Final_Detail_Analysis_"
        f"{start_date.isoformat()}_{end_date.isoformat()}"
    )

    hierarchy_path = (
        period_dir
        / f"{output_prefix}_Hierarchy.csv"
    )

    summary_path = (
        period_dir
        / f"{output_prefix}_Summary.csv"
    )

    device_category_path = (
        period_dir
        / f"{output_prefix}_Device_Category.csv"
    )

    daily_path = (
        period_dir
        / f"{output_prefix}_Daily.csv"
    )

    off_device_path = (
        period_dir
        / f"{output_prefix}_Off_Device.csv"
    )

    report_path = (
        period_dir
        / f"{output_prefix}_Report.txt"
    )

    write_csv(
        hierarchy_path,
        hierarchy,
        HIERARCHY_FIELDS,
        args.force,
    )

    write_csv(
        summary_path,
        summaries,
        SUMMARY_FIELDS,
        args.force,
    )

    write_csv(
        device_category_path,
        device_category,
        [
            "Device",
            "Category",
            "Duration_sec",
            "Duration_min",
            "Percent_of_Total",
        ],
        args.force,
    )

    write_csv(
        daily_path,
        daily,
        DAILY_FIELDS,
        args.force,
    )

    write_csv(
        off_device_path,
        off_device,
        HIERARCHY_FIELDS,
        args.force,
    )

    report = build_report(
        records,
        start_date,
        end_date,
        hierarchy,
        summaries,
        device_category,
    )

    if report_path.exists() and not args.force:
        raise FileExistsError(
            f"Output already exists: {report_path}. "
            "Use --force to overwrite."
        )

    report_path.write_text(
        report,
        encoding="utf-8",
    )

    print("")
    print("=== DETAIL ANALYSIS SUMMARY ===")
    print(f"Hierarchy rows       : {len(hierarchy)}")
    print(f"Summary rows         : {len(summaries)}")
    print(f"Device/category rows : {len(device_category)}")
    print(f"Daily rows           : {len(daily)}")
    print(f"Off-device rows      : {len(off_device)}")
    print("")
    print(f"Hierarchy : {hierarchy_path}")
    print(f"Summary   : {summary_path}")
    print(f"Device × Category: {device_category_path}")
    print(f"Daily     : {daily_path}")
    print(f"Off-device: {off_device_path}")
    print(f"Report    : {report_path}")
    print("")
    print("RESULT: DETAIL ANALYSIS GENERATED.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())