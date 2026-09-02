#!/usr/bin/env python3
"""Compare two frozen System Tracker final-analysis periods."""

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
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT
    / "output"
    / "Integrated"
    / "Analysis"
    / "Variation"
)

DATE_FORMAT = "%Y-%m-%d"
SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0
PERCENT_EPSILON = 1e-9

DIMENSIONS = {
    "Device": ("Device",),
    "Category": ("Category",),
    "Domain": ("Domain",),
    "Energy": ("Energy",),
    "Goal": ("Goal",),
    "Device × Category": ("Device", "Category"),
    "Category × Subcategory": ("Category", "Subcategory"),
    "Category × Subcategory × Domain": (
        "Category",
        "Subcategory",
        "Domain",
    ),
    "Deepest Hierarchy": (
        "Device",
        "Category",
        "Subcategory",
        "Domain",
        "Energy",
        "Goal",
    ),
}


@dataclass(frozen=True)
class FinalRecord:
    """Represent one positive-duration final analytical record."""

    date: str
    device: str
    source: str
    category: str
    subcategory: str
    domain: str
    energy: str
    goal: str
    duration_sec: float


@dataclass(frozen=True)
class Period:
    """Represent one comparison period."""

    name: str
    start: date
    end: date
    path: Path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare two frozen System Tracker final-analysis periods."
        )
    )
    parser.add_argument(
        "--period-a-start",
        required=True,
        help="Period A start date: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--period-a-end",
        required=True,
        help="Period A end date: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--period-b-start",
        required=True,
        help="Period B start date: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--period-b-end",
        required=True,
        help="Period B end date: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--final-root",
        default=str(DEFAULT_FINAL_ROOT),
        help="Root directory containing frozen final-analysis outputs.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for variation-analysis outputs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing variation-analysis outputs.",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    """Parse an ISO-formatted date."""
    try:
        return datetime.strptime(
            value.strip(),
            DATE_FORMAT,
        ).date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def period_label(start: date, end: date) -> str:
    """Return a standard period label."""
    return f"{start.isoformat()}_{end.isoformat()}"


def format_duration(seconds: float) -> str:
    """Format seconds as hours and minutes."""
    total_minutes = int(round(seconds / SECONDS_PER_MINUTE))
    hours, minutes = divmod(total_minutes, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"

    return f"{minutes}m"


def format_signed_duration(seconds: float) -> str:
    """Format a signed duration as hours and minutes."""
    sign = "+" if seconds > 0 else "-" if seconds < 0 else ""
    return f"{sign}{format_duration(abs(seconds))}"


def format_percent(value: float | None) -> str:
    """Format a percentage value."""
    if value is None or not math.isfinite(value):
        return "N/A"
    return f"{value:+.2f}%"


def parse_float(value: object) -> float:
    """Parse a numeric value."""
    if value is None:
        return 0.0

    text = str(value).strip()
    if not text:
        return 0.0

    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc


def normalize(value: object) -> str:
    """Normalize a CSV value to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def resolve_field(
    fieldnames: Sequence[str],
    candidates: Sequence[str],
) -> str:
    """Return the first matching field name."""
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    return ""


def resolve_duration_column(fieldnames: Sequence[str]) -> str:
    """Resolve the final-analysis duration column."""
    return resolve_field(
        fieldnames,
        (
            "Duration_sec",
            "Duration_seconds",
            "Duration",
        ),
    )


def find_final_csv(
    final_root: Path,
    start: date,
    end: date,
) -> Path:
    """Locate a frozen final-analysis CSV."""
    period_dir = final_root / period_label(start, end)
    expected = (
        period_dir
        / f"Final_Analysis_{period_label(start, end)}.csv"
    )

    if expected.is_file():
        return expected

    candidates = sorted(
        period_dir.glob("Final_Analysis_*.csv")
    )

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise FileNotFoundError(
            f"No frozen final-analysis CSV found in {period_dir}"
        )

    raise FileNotFoundError(
        f"Unable to determine final-analysis CSV in {period_dir}. "
        f"Expected {expected}."
    )


def load_final_records(
    path: Path,
    start: date,
    end: date,
) -> list[FinalRecord]:
    """Load positive-duration final records for a period."""
    records: list[FinalRecord] = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        fieldnames = reader.fieldnames
        date_field = resolve_field(fieldnames, ("Date", "date"))
        duration_field = resolve_duration_column(fieldnames)

        if not date_field:
            raise ValueError(f"Final analysis has no Date column: {path}")

        if not duration_field:
            raise ValueError(
                f"Final analysis has no supported duration column: {path}"
            )

        fields = {
            name: resolve_field(
                fieldnames,
                (name, name.lower()),
            )
            for name in (
                "Device",
                "Source",
                "Category",
                "Subcategory",
                "Domain",
                "Energy",
                "Goal",
            )
        }

        for row_number, row in enumerate(reader, start=2):
            raw_date = normalize(row.get(date_field))
            if not raw_date:
                continue

            row_date = parse_date(raw_date)

            if not start <= row_date <= end:
                continue

            duration_sec = parse_float(row.get(duration_field))
            if duration_sec <= 0:
                continue

            values = {
                name: normalize(row.get(field))
                for name, field in fields.items()
            }

            device = values["Device"] or values["Source"] or "Unknown"
            category = values["Category"] or "Uncategorized"

            records.append(
                FinalRecord(
                    date=row_date.isoformat(),
                    device=device,
                    source=values["Source"],
                    category=category,
                    subcategory=values["Subcategory"],
                    domain=values["Domain"],
                    energy=values["Energy"],
                    goal=values["Goal"],
                    duration_sec=duration_sec,
                )
            )

    if not records:
        raise ValueError(
            f"No positive final analytical records found in {path} "
            f"for {start.isoformat()} -> {end.isoformat()}."
        )

    return records


def aggregate(
    records: Iterable[FinalRecord],
    fields: Sequence[str],
) -> dict[tuple[str, ...], float]:
    """Aggregate duration by selected record fields."""
    totals: dict[tuple[str, ...], float] = defaultdict(float)

    for record in records:
        values = {
            "Date": record.date,
            "Device": record.device,
            "Source": record.source,
            "Category": record.category,
            "Subcategory": record.subcategory,
            "Domain": record.domain,
            "Energy": record.energy,
            "Goal": record.goal,
        }

        key = tuple(values[field] for field in fields)
        totals[key] += record.duration_sec

    return dict(totals)


def percent_change(
    period_a: float,
    period_b: float,
) -> float | None:
    """Calculate B-versus-A percentage change."""
    if abs(period_a) <= PERCENT_EPSILON:
        if abs(period_b) <= PERCENT_EPSILON:
            return 0.0
        return None

    return (period_b - period_a) / period_a * 100.0


def build_comparison_rows(
    records_a: Sequence[FinalRecord],
    records_b: Sequence[FinalRecord],
    fields: Sequence[str],
) -> list[dict[str, object]]:
    """Build a period-A versus period-B comparison table."""
    totals_a = aggregate(records_a, fields)
    totals_b = aggregate(records_b, fields)
    keys = sorted(
        set(totals_a) | set(totals_b),
        key=lambda key: (
            -(totals_b.get(key, 0.0) - totals_a.get(key, 0.0)),
            key,
        ),
    )

    total_a = sum(record.duration_sec for record in records_a)
    total_b = sum(record.duration_sec for record in records_b)

    rows: list[dict[str, object]] = []

    for key in keys:
        duration_a = totals_a.get(key, 0.0)
        duration_b = totals_b.get(key, 0.0)
        delta = duration_b - duration_a

        share_a = (
            duration_a / total_a * 100.0
            if total_a > 0
            else 0.0
        )
        share_b = (
            duration_b / total_b * 100.0
            if total_b > 0
            else 0.0
        )

        if duration_a <= PERCENT_EPSILON and duration_b > 0:
            status = "NEW"
        elif duration_a > 0 and duration_b <= PERCENT_EPSILON:
            status = "DISAPPEARED"
        elif abs(delta) <= PERCENT_EPSILON:
            status = "UNCHANGED"
        elif delta > 0:
            status = "INCREASED"
        else:
            status = "DECREASED"

        values = dict(zip(fields, key))

        rows.append(
            {
                **{
                    field: values.get(field, "")
                    for field in fields
                },
                "Period_A_sec": round(duration_a, 3),
                "Period_A_min": round(
                    duration_a / SECONDS_PER_MINUTE,
                    3,
                ),
                "Period_A_share_pct": round(share_a, 3),
                "Period_B_sec": round(duration_b, 3),
                "Period_B_min": round(
                    duration_b / SECONDS_PER_MINUTE,
                    3,
                ),
                "Period_B_share_pct": round(share_b, 3),
                "Change_sec": round(delta, 3),
                "Change_min": round(
                    delta / SECONDS_PER_MINUTE,
                    3,
                ),
                "Change_pct": (
                    round(percent_change(duration_a, duration_b), 3)
                    if percent_change(duration_a, duration_b) is not None
                    else ""
                ),
                "Share_change_pct_points": round(
                    share_b - share_a,
                    3,
                ),
                "Status": status,
            }
        )

    return rows


def write_csv(
    path: Path,
    rows: Sequence[dict[str, object]],
    fields: Sequence[str],
    force: bool,
) -> None:
    """Write a comparison CSV."""
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
            fieldnames=list(fields),
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def comparison_fields(fields: Sequence[str]) -> list[str]:
    """Return output columns for a comparison table."""
    return [
        *fields,
        "Period_A_sec",
        "Period_A_min",
        "Period_A_share_pct",
        "Period_B_sec",
        "Period_B_min",
        "Period_B_share_pct",
        "Change_sec",
        "Change_min",
        "Change_pct",
        "Share_change_pct_points",
        "Status",
    ]


def daily_summary(
    records: Sequence[FinalRecord],
) -> dict[str, float]:
    """Return total analytical duration by day."""
    totals: dict[str, float] = defaultdict(float)

    for record in records:
        totals[record.date] += record.duration_sec

    return dict(totals)


def top_changes(
    rows: Sequence[dict[str, object]],
    limit: int = 10,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the largest increases and decreases."""
    increases = sorted(
        (
            row
            for row in rows
            if float(row["Change_sec"]) > PERCENT_EPSILON
        ),
        key=lambda row: -float(row["Change_sec"]),
    )[:limit]

    decreases = sorted(
        (
            row
            for row in rows
            if float(row["Change_sec"]) < -PERCENT_EPSILON
        ),
        key=lambda row: float(row["Change_sec"]),
    )[:limit]

    return increases, decreases


def row_label(
    row: dict[str, object],
    fields: Sequence[str],
) -> str:
    """Build a readable label for a comparison row."""
    values = [
        normalize(row.get(field))
        for field in fields
    ]
    return " → ".join(value or "(blank)" for value in values)


def build_report(
    period_a: Period,
    period_b: Period,
    records_a: Sequence[FinalRecord],
    records_b: Sequence[FinalRecord],
    comparisons: dict[str, list[dict[str, object]]],
) -> str:
    """Build the human-readable variation report."""
    total_a = sum(record.duration_sec for record in records_a)
    total_b = sum(record.duration_sec for record in records_b)

    days_a = (period_a.end - period_a.start).days + 1
    days_b = (period_b.end - period_b.start).days + 1

    daily_a = daily_summary(records_a)
    daily_b = daily_summary(records_b)

    avg_a = total_a / days_a
    avg_b = total_b / days_b

    lines = [
        "=== VARIATION ANALYSIS ===",
        "",
        f"Period A : {period_a.start.isoformat()} -> "
        f"{period_a.end.isoformat()} ({days_a} days)",
        f"Period B : {period_b.start.isoformat()} -> "
        f"{period_b.end.isoformat()} ({days_b} days)",
        "",
        "=== OVERALL ===",
        f"Analytical duration A : {format_duration(total_a)}",
        f"Analytical duration B : {format_duration(total_b)}",
        f"Change                 : {format_signed_duration(total_b - total_a)}",
        (
            f"Change %               : "
            f"{format_percent(percent_change(total_a, total_b))}"
        ),
        f"Average per day A      : {format_duration(avg_a)}",
        f"Average per day B      : {format_duration(avg_b)}",
        (
            f"Daily average change   : "
            f"{format_signed_duration(avg_b - avg_a)}"
        ),
        f"Final records A        : {len(records_a)}",
        f"Final records B        : {len(records_b)}",
        (
            f"Record-count change    : "
            f"{len(records_b) - len(records_a):+d}"
        ),
        f"Active days A          : {len(daily_a)}",
        f"Active days B          : {len(daily_b)}",
        "",
    ]

    for dimension, fields in DIMENSIONS.items():
        rows = comparisons[dimension]
        increases, decreases = top_changes(rows)

        lines.extend(
            [
                f"=== {dimension.upper()} ===",
                f"Rows compared: {len(rows)}",
                "",
                "Top increases:",
            ]
        )

        if increases:
            for row in increases:
                change_pct = (
                    float(row["Change_pct"])
                    if row["Change_pct"] != ""
                    else None
                )
                lines.append(
                    f"+ {row_label(row, fields)}: "
                    f"{format_signed_duration(float(row['Change_sec']))} "
                    f"({format_percent(change_pct)})"
                )
        else:
            lines.append("None.")

        lines.append("")
        lines.append("Top decreases:")

        if decreases:
            for row in decreases:
                change_pct = (
                    float(row["Change_pct"])
                    if row["Change_pct"] != ""
                    else None
                )
                lines.append(
                    f"- {row_label(row, fields)}: "
                    f"{format_signed_duration(float(row['Change_sec']))} "
                    f"({format_percent(change_pct)})"
                )
        else:
            lines.append("None.")

        lines.append("")

    lines.extend(
        [
            "=== INTERPRETATION ===",
            "",
            "Variation Analysis is descriptive only.",
            "It compares frozen final-analysis outputs and does not "
            "modify reconciliation or taxonomy.",
            "",
            "Use absolute change and daily-average change together "
            "when the two periods have different lengths.",
            "",
            "Taxonomy candidates from EDA remain diagnostic and are "
            "not automatically changed by this analysis.",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    """Run variation analysis."""
    args = parse_args()

    period_a_start = parse_date(args.period_a_start)
    period_a_end = parse_date(args.period_a_end)
    period_b_start = parse_date(args.period_b_start)
    period_b_end = parse_date(args.period_b_end)

    if period_a_end < period_a_start:
        raise ValueError("Period A end date cannot precede its start date.")

    if period_b_end < period_b_start:
        raise ValueError("Period B end date cannot precede its start date.")

    final_root = Path(args.final_root).resolve()
    output_root = Path(args.output_root).resolve()

    period_a = Period(
        name="Period A",
        start=period_a_start,
        end=period_a_end,
        path=find_final_csv(
            final_root,
            period_a_start,
            period_a_end,
        ),
    )

    period_b = Period(
        name="Period B",
        start=period_b_start,
        end=period_b_end,
        path=find_final_csv(
            final_root,
            period_b_start,
            period_b_end,
        ),
    )

    output_dir = (
        output_root
        / f"{period_label(period_a.start, period_a.end)}"
        f"_vs_{period_label(period_b.start, period_b.end)}"
    )

    records_a = load_final_records(
        period_a.path,
        period_a.start,
        period_a.end,
    )
    records_b = load_final_records(
        period_b.path,
        period_b.start,
        period_b.end,
    )

    comparisons: dict[str, list[dict[str, object]]] = {}

    for dimension, fields in DIMENSIONS.items():
        comparisons[dimension] = build_comparison_rows(
            records_a,
            records_b,
            fields,
        )

    print("=== Variation Analysis ===")
    print(
        f"Period A : {period_a.start.isoformat()} -> "
        f"{period_a.end.isoformat()}"
    )
    print(
        f"Period B : {period_b.start.isoformat()} -> "
        f"{period_b.end.isoformat()}"
    )
    print(f"Input A  : {period_a.path}")
    print(f"Input B  : {period_b.path}")

    output_files: list[Path] = []

    for dimension, rows in comparisons.items():
        filename = (
            "Variation_"
            + dimension.replace(" × ", "_x_")
            .replace(" ", "_")
            .replace("→", "_")
            .replace("×", "x")
            + ".csv"
        )

        path = output_dir / filename

        write_csv(
            path,
            rows,
            comparison_fields(DIMENSIONS[dimension]),
            args.force,
        )
        output_files.append(path)

    report_path = (
        output_dir
        / (
            "Variation_Analysis_"
            f"{period_label(period_a.start, period_a.end)}"
            "_vs_"
            f"{period_label(period_b.start, period_b.end)}.txt"
        )
    )

    report = build_report(
        period_a,
        period_b,
        records_a,
        records_b,
        comparisons,
    )

    if report_path.exists() and not args.force:
        raise FileExistsError(
            f"Output already exists: {report_path}. "
            "Use --force to overwrite."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        report,
        encoding="utf-8",
    )

    print("")
    print("=== VARIATION ANALYSIS SUMMARY ===")
    print(f"Records A       : {len(records_a)}")
    print(f"Records B       : {len(records_b)}")
    print(
        f"Duration A      : "
        f"{format_duration(sum(r.duration_sec for r in records_a))}"
    )
    print(
        f"Duration B      : "
        f"{format_duration(sum(r.duration_sec for r in records_b))}"
    )
    duration_a = sum(
        record.duration_sec
        for record in records_a
    )
    duration_b = sum(
        record.duration_sec
        for record in records_b
    )
    duration_change = (
        sum(record.duration_sec for record in records_b)
        - sum(record.duration_sec for record in records_a)
    )
    print(
        f"Duration change : "
        f"{format_signed_duration(duration_change)}"
    )
    print(f"Output directory: {output_dir}")
    print(f"Report          : {report_path}")
    print("")
    print("RESULT: VARIATION ANALYSIS GENERATED.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
