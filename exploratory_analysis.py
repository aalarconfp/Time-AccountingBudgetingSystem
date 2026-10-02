# FILE: exploratory_analysis.py

"""Generate exploratory diagnostics from the reconciled final hierarchy."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent
FINAL_ANALYSIS_ROOT = (
    PROJECT_ROOT / "output" / "Integrated" / "Analysis" / "Final"
)
EDA_ROOT = (
    PROJECT_ROOT / "output" / "Integrated" / "Analysis" / "EDA"
)

CSV_ENCODING = "utf-8-sig"
DAY_SECONDS = 24 * 60 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate exploratory analysis from final reconciled hierarchy."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def period_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        raise ValueError("end-date must be on or after start-date.")
    return (end_date - start_date).days + 1


def final_directory(start_date: date, end_date: date) -> Path:
    return FINAL_ANALYSIS_ROOT / (
        f"{start_date.isoformat()}_{end_date.isoformat()}"
    )


def eda_directory(start_date: date, end_date: date) -> Path:
    return EDA_ROOT / (
        f"{start_date.isoformat()}_{end_date.isoformat()}"
    )


def hierarchy_path(start_date: date, end_date: date) -> Path:
    return final_directory(start_date, end_date) / (
        "Final_Analysis_By_Device_Category_Subcategory_Domain_Energy_Goal_"
        f"{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )


def time_universe_path(start_date: date, end_date: date) -> Path:
    return final_directory(start_date, end_date) / (
        "Final_Time_Universe_Reconciliation_"
        f"{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding=CSV_ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def number(value: object) -> float:
    try:
        return float(str(value).strip() or 0)
    except ValueError:
        return 0.0


def duration_text(seconds: float) -> str:
    total_minutes = int(round(seconds / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


def percent(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return value * 100.0 / total


def deepest_rows(
    hierarchy: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return the deepest analytical level without re-aggregating hierarchy rows."""
    expected = (
        "Device → Category → Subcategory → Domain → Energy → Goal"
    )
    return [
        row
        for row in hierarchy
        if row.get("Analysis_Level", "") == expected
    ]


def aggregate(
    rows: Iterable[dict[str, str]],
    dimension_names: tuple[str, ...],
) -> list[dict[str, object]]:
    totals: defaultdict[tuple[str, ...], float] = defaultdict(float)

    for row in rows:
        key = tuple(row.get(name, "").strip() for name in dimension_names)
        totals[key] += number(row.get("Duration_sec"))

    grand_total = sum(totals.values())
    output: list[dict[str, object]] = []

    for rank, (key, seconds) in enumerate(
        sorted(totals.items(), key=lambda item: item[1], reverse=True),
        start=1,
    ):
        item = {
            name.lower(): value
            for name, value in zip(dimension_names, key)
        }
        item.update(
            {
                "Duration_sec": round(seconds, 3),
                "Duration_min": round(seconds / 60.0, 3),
                "Percent_of_Total": round(percent(seconds, grand_total), 3),
                "Rank": rank,
            }
        )
        output.append(item)

    return output


def concentration(rows: list[dict[str, str]], dimension: str) -> dict[str, object]:
    values = [
        number(row["Duration_sec"])
        for row in aggregate(rows, (dimension,))
    ]
    total = sum(values)
    shares = [value / total for value in values] if total else []

    return {
        "Dimension": dimension,
        "Top_1_percent": round(sum(shares[:1]) * 100, 3),
        "Top_3_percent": round(sum(shares[:3]) * 100, 3),
        "Top_5_percent": round(sum(shares[:5]) * 100, 3),
        "HHI": round(sum(share * share for share in shares), 5),
    }


def taxonomy_candidates(
    rows: list[dict[str, str]],
    total_seconds: float,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    for row in aggregate(
        rows,
        ("Category", "Subcategory", "Domain", "Energy", "Goal"),
    ):
        share = number(row["Percent_of_Total"])
        seconds = number(row["Duration_sec"])
        reasons: list[str] = []

        if share >= 1.0:
            reasons.append("LARGE_TIME_CONTRIBUTOR")
        if share >= 0.5:
            reasons.append("SIGNIFICANT_ANALYTICAL_NODE")
        if row["category"] == "Off-Device Life":
            reasons.append("OFF_DEVICE_REVIEW")
        if "Uncategorized" in (
            row["subcategory"],
            row["category"],
        ):
            reasons.append("UNCATEGORIZED_REVIEW")

        if reasons:
            candidates.append(
                {
                    "Category": row["category"],
                    "Subcategory": row["subcategory"],
                    "Domain": row["domain"],
                    "Energy": row["energy"],
                    "Goal": row["goal"],
                    "Duration_sec": round(seconds, 3),
                    "Duration_min": round(seconds / 60.0, 3),
                    "Percent_of_Total": share,
                    "Review_Reasons": ";".join(dict.fromkeys(reasons)),
                }
            )

    return candidates


def load_time_universe(
    path: Path,
) -> tuple[float, float, float, float, float]:
    """Return capacity, corrected tracked, unique tracked, off-device, overlap."""
    rows = read_csv(path)

    capacity = 0.0
    corrected = 0.0
    unique = 0.0
    off_device = 0.0
    overlap = 0.0

    for row in rows:
        if row.get("Time_Bucket") == "Period Capacity":
            capacity += number(row.get("Capacity_min")) * 60.0

        if row.get("Time_Bucket") == "Period Capacity":
            overlap += number(row.get("Overlap_min")) * 60.0

        if row.get("Time_Bucket") == "Off-Device / Untracked Residual":
            off_device += number(
                row.get("Analytical_Off_Device_min")
                or row.get("Gross_Residual_min")
            ) * 60.0

    if not capacity:
        period_capacity_rows = [
            row
            for row in rows
            if row.get("Time_Bucket") == "Period Capacity"
        ]
        capacity = len(period_capacity_rows) * DAY_SECONDS

    corrected = sum(
        number(row.get("Corrected_Tracked_min")) * 60.0
        for row in rows
        if row.get("Time_Bucket") == "Period Capacity"
    )

    unique = max(0.0, corrected - overlap)

    return capacity, corrected, unique, off_device, overlap


def build_report(
    start_date: date,
    end_date: date,
    deepest: list[dict[str, str]],
    capacity: float,
    corrected: float,
    unique: float,
    off_device: float,
    overlap: float,
    device_rows: list[dict[str, object]],
    category_rows: list[dict[str, object]],
    domain_rows: list[dict[str, object]],
    energy_rows: list[dict[str, object]],
    goal_rows: list[dict[str, object]],
    top_rows: list[dict[str, object]],
    candidates: list[dict[str, object]],
) -> str:
    days = period_days(start_date, end_date)
    analytical_total = sum(number(row["Duration_sec"]) for row in deepest)

    maintenance = sum(
        number(row["Duration_sec"])
        for row in deepest
        if row.get("Goal") == "Maintenance"
    )
    recovery = sum(
        number(row["Duration_sec"])
        for row in deepest
        if row.get("Energy") == "Recovery"
    )
    deep = sum(
        number(row["Duration_sec"])
        for row in deepest
        if row.get("Energy") == "Deep"
    )
    passive = sum(
        number(row["Duration_sec"])
        for row in deepest
        if row.get("Energy") == "Passive"
    )

    lines = [
        "EXPLORATORY DATA ANALYSIS",
        "Personal Time / Habit & Wellness System",
        "",
        f"Period: {start_date} -> {end_date}",
        f"Days: {days}",
        "",
        "IMPORTANT:",
        "This is an exploratory diagnostic report.",
        "It does not modify the reconciled analytical dataset.",
        "The accounting/time-universe layer remains the source of truth",
        "for elapsed capacity, unique tracked time, overlap, and residual time.",
        "",
        "=" * 78,
        "1. TIME UNIVERSE",
        "=" * 78,
        f"Capacity:              {duration_text(capacity)}",
        f"Analytical total:      {duration_text(analytical_total)}",
        f"Tracked unique:        {duration_text(unique)}",
        f"Off-device life:       {duration_text(off_device)}",
        f"Tracked overlap:      {duration_text(overlap)}",
        f"Analytical coverage:   {percent(analytical_total, capacity):.2f}%",
        "",
        "Analytical total may exceed elapsed capacity because the hierarchy",
        "contains observed analytical activity and is not a mutually exclusive",
        "clock ledger. Use the time-universe values for elapsed-time accounting.",
        "",
        "=" * 78,
        "2. PRIMARY SIGNALS",
        "=" * 78,
        f"Maintenance:            {duration_text(maintenance)} "
        f"({percent(maintenance, analytical_total):.2f}%)",
        f"Recovery:               {duration_text(recovery)} "
        f"({percent(recovery, analytical_total):.2f}%)",
        f"Deep energy:            {duration_text(deep)} "
        f"({percent(deep, analytical_total):.2f}%)",
        f"Passive energy:         {duration_text(passive)} "
        f"({percent(passive, analytical_total):.2f}%)",
        "",
        "=" * 78,
        "3. DAILY AVERAGE CHECK",
        "=" * 78,
        f"Maintenance/day:        {maintenance / days / 60:.1f} min/day",
        f"Recovery/day:           {recovery / days / 60:.1f} min/day",
        f"Deep energy/day:        {deep / days / 60:.1f} min/day",
        f"Passive energy/day:     {passive / days / 60:.1f} min/day",
        "",
        "=" * 78,
        "4. DEVICE",
        "=" * 78,
    ]

    for index, row in enumerate(device_rows, 1):
        lines.append(
            f"{index:>2}. device={row['device']} | "
            f"Duration_min={row['Duration_min']} | "
            f"Percent={row['Percent_of_Total']}"
        )

    sections = (
        ("5. CATEGORY", category_rows, "category"),
        ("6. DOMAIN", domain_rows, "domain"),
        ("7. ENERGY", energy_rows, "energy"),
        ("8. GOAL", goal_rows, "goal"),
    )

    for title, rows, field in sections:
        lines.extend(["", "=" * 78, title, "=" * 78])
        for index, row in enumerate(rows, 1):
            lines.append(
                f"{index:>2}. {field}={row[field]} | "
                f"Duration_min={row['Duration_min']} | "
                f"Percent={row['Percent_of_Total']}"
            )

    lines.extend(["", "=" * 78, "9. TOP ANALYTICAL ACTIVITIES", "=" * 78])
    for index, row in enumerate(top_rows[:30], 1):
        lines.append(
            f"{index:>2}. "
            f"device={row['device']} | category={row['category']} | "
            f"subcategory={row['subcategory']} | domain={row['domain']} | "
            f"energy={row['energy']} | goal={row['goal']} | "
            f"Duration_min={row['Duration_min']} | "
            f"Percent={row['Percent_of_Total']}"
        )

    lines.extend(["", "=" * 78, "10. CONCENTRATION", "=" * 78])
    for dimension in ("Category", "Subcategory", "Domain", "Energy", "Goal"):
        result = concentration(deepest, dimension)
        lines.append(
            f"{dimension}: Top1={result['Top_1_percent']:.2f}% | "
            f"Top3={result['Top_3_percent']:.2f}% | "
            f"Top5={result['Top_5_percent']:.2f}% | "
            f"HHI={result['HHI']:.5f}"
        )

    lines.extend(
        [
            "",
            "=" * 78,
            "11. TAXONOMY REVIEW CANDIDATES",
            "=" * 78,
        ]
    )
    for index, row in enumerate(candidates, 1):
        lines.append(
            f"{index:>2}. "
            f"{row['Category']} / {row['Subcategory']} / "
            f"{row['Domain']} / {row['Energy']} / {row['Goal']} | "
            f"{row['Duration_min']} min | "
            f"{row['Percent_of_Total']}% | "
            f"{row['Review_Reasons']}"
        )

    lines.extend(
        [
            "",
            "=" * 78,
            "12. INTERPRETATION GUIDANCE",
            "=" * 78,
            "1. Review large nodes before changing their taxonomy.",
            "2. Separate taxonomy problems from genuinely large behaviors.",
            "3. Treat Off-Device Life as meaningful human-life maintenance,",
            "   not as discarded or missing time.",
            "4. Investigate Uncategorized and generic buckets separately.",
            "5. Use repeated periods before interpreting burnout or workload trends.",
            "",
            "The recurring KPI report should use a small, stable KPI set.",
            "This EDA remains the diagnostic layer for deeper questions.",
            "",
            "=" * 78,
            "END OF EDA REPORT",
            "=" * 78,
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    hierarchy_file = hierarchy_path(start_date, end_date)
    universe_file = time_universe_path(start_date, end_date)
    output_dir = eda_directory(start_date, end_date)

    if not hierarchy_file.exists():
        raise FileNotFoundError(f"Missing hierarchy CSV: {hierarchy_file}")
    if not universe_file.exists():
        raise FileNotFoundError(f"Missing time-universe CSV: {universe_file}")

    if output_dir.exists() and not args.force:
        raise FileExistsError(
            f"EDA output already exists: {output_dir}. Use --force to replace it."
        )

    hierarchy = read_csv(hierarchy_file)
    deepest = deepest_rows(hierarchy)
    if not deepest:
        raise ValueError("No deepest hierarchy rows were found.")

    capacity, corrected, unique, off_device, overlap = load_time_universe(
        universe_file
    )

    device_rows = aggregate(deepest, ("Device",))
    category_rows = aggregate(deepest, ("Category",))
    domain_rows = aggregate(deepest, ("Domain",))
    energy_rows = aggregate(deepest, ("Energy",))
    goal_rows = aggregate(deepest, ("Goal",))

    domain_energy_rows = aggregate(deepest, ("Domain", "Energy"))
    domain_goal_rows = aggregate(deepest, ("Domain", "Goal"))
    top_rows = aggregate(
        deepest,
        ("Device", "Category", "Subcategory", "Domain", "Energy", "Goal"),
    )
    candidates = taxonomy_candidates(
        deepest,
        sum(number(row["Duration_sec"]) for row in deepest),
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / "EDA_Device.csv", device_rows)
    write_csv(output_dir / "EDA_Category.csv", category_rows)
    write_csv(output_dir / "EDA_Domain.csv", domain_rows)
    write_csv(output_dir / "EDA_Energy.csv", energy_rows)
    write_csv(output_dir / "EDA_Goal.csv", goal_rows)
    write_csv(output_dir / "EDA_Domain_Energy.csv", domain_energy_rows)
    write_csv(output_dir / "EDA_Domain_Goal.csv", domain_goal_rows)
    write_csv(output_dir / "EDA_Top_Activities.csv", top_rows)
    write_csv(output_dir / "EDA_Taxonomy_Review_Candidates.csv", candidates)

    report = build_report(
        start_date,
        end_date,
        deepest,
        capacity,
        corrected,
        unique,
        off_device,
        overlap,
        device_rows,
        category_rows,
        domain_rows,
        energy_rows,
        goal_rows,
        top_rows,
        candidates,
    )

    report_path = output_dir / (
        f"Exploratory_Analysis_{start_date.isoformat()}_{end_date.isoformat()}.txt"
    )
    write_text(report_path, report)

    analytical_total = sum(number(row["Duration_sec"]) for row in deepest)

    print("=== Exploratory Data Analysis ===")
    print(f"Dates              : {start_date} -> {end_date}")
    print(f"Deepest rows       : {len(deepest)}")
    print(f"Analytical duration : {duration_text(analytical_total)}")
    print(f"Capacity            : {duration_text(capacity)}")
    print(f"EDA output          : {output_dir}")
    print(f"EDA report          : {report_path}")
    print(f"Flags               : 0")
    print(f"Taxonomy candidates : {len(candidates)}")
    print("RESULT: EXPLORATORY ANALYSIS GENERATED.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())