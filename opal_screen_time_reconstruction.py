# opal_screen_time_reconstruction.py
"""Reconstruct missing Apple Screen Time from Opal weekly reports.

This is NOT Apple Screen Time ingestion. It is a separate, auditable
estimation layer for dates whose original Apple Screen Time evidence was lost.

Flow
----
1. Read the transcription of Opal weekly reports
   (``input/iPhone/Opal/Opal_Weekly_Reports.csv``). Each report is a Monday ->
   Sunday bar chart; values map to calendar dates only when the week is
   established (header label, or 'Last Week' relative to the capture date).
2. Calibrate Opal against canonical August Apple Screen Time Daily_Time on
   dates where both exist.
3. Estimate Apple-equivalent daily totals for the missing period with the
   pre-specified additive model:  Apple_est = Opal + mean(Apple - Opal).
   Multiplicative and regression models are reported for comparison only.
4. Allocate each estimated total across the Apple Screen Time categories
   using historically observed Apple category proportions (August Daily_Time).
   Weekday-specific proportions are used only when each weekday has enough
   history; equal / overall / weekday allocation are validated
   retrospectively on August (leave-one-day-out).
5. Compare August with the observed September Apple category mix that
   survived the phone replacement (validation reference only).

Safety
------
- Writes only to its own reconstruction directory under output/Analysis.
- Never writes Raw / Fact / Daily outputs and never modifies Apple data.
- A missing-period date that already has observed Apple Daily_Time is never
  estimated.
- A date without valid Opal evidence is REVIEW and has no value (never zero).
- Outputs contain no timestamps, so identical inputs give identical files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent

DEFAULT_OPAL_REPORTS = PROJECT_ROOT / "input" / "iPhone" / "Opal" / "Opal_Weekly_Reports.csv"
DEFAULT_SEPTEMBER_REFERENCE = (
    PROJECT_ROOT / "input" / "iPhone" / "Reconstruction" / "Apple_September_Observed_Reference.csv"
)
DEFAULT_SCREENSHOT_ROOT = PROJECT_ROOT / "input" / "iPhone" / "ScreenTime"
DEFAULT_APPLE_DAILY_DIR = (
    PROJECT_ROOT / "output" / "Daily" / "Time" / "AppleScreenTime" / "iPhone"
)
RECONSTRUCTION_ROOT = (
    PROJECT_ROOT / "output" / "Analysis" / "Reconstruction" / "Opal_AppleScreenTime"
)
PROTECTED_OUTPUT_ROOTS = tuple(
    PROJECT_ROOT / "output" / name for name in ("Raw", "Fact", "Daily", "Integrated")
)

METHOD_VERSION = "OPAL_ADDITIVE_HISTCAT_v2"
SOURCE = "iphone"
SOURCE_DETAIL = "AppleScreenTime_Estimated"
ALLOCATION_TYPE = "Estimated"
EVIDENCE_TYPE = "Opal_Calibrated_Estimate"
EVIDENCE_SOURCE = "Opal + August Apple Screen Time calibration"
ESTIMATION_METHOD = "Opal + August mean daily Apple-minus-Opal correction"
CATEGORY_ALLOCATION = "Historical Apple category distribution"
EVIDENCE_QUALITY = "Estimated / reconstructed"

MODEL_EQUAL = "EQUAL_CATEGORY"
MODEL_OVERALL = "HISTORICAL_OVERALL_POOLED"
MODEL_WEEKDAY = "HISTORICAL_WEEKDAY_POOLED"

# Apple Screen Time top-level categories as stored in the project's canonical
# iPhone Daily_Time (Apple's own names; Apple's "Social" is stored as
# "Social Networking"). Fixed order keeps allocation deterministic.
APPLE_SCREEN_TIME_CATEGORIES: tuple[str, ...] = (
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
    "Other",
)
# Builder-derived residual (Apple headline minus visible categories).
RESIDUAL_SUBCATEGORY = "Screen Time / System"

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MAPPING_BASES = {"HEADER_LABEL", "LAST_WEEK_RELATIVE_TO_CAPTURE"}
MAPPING_STATUSES = {"CONFIRMED", "INFERRED", "UNKNOWN"}
TRANSCRIPTION_STATUSES = {"VERIFIED", "PENDING_HUMAN_REVIEW"}
# Opal bar labels are rounded (observed steps of 5 and 15 minutes), so the
# seven-bar mean can differ slightly from the header average.
HEADER_AVERAGE_TOLERANCE_MIN = 3.0
# Pre-specified support rule: weekday-specific proportions need at least this
# many observed days for every weekday (i.e. roughly two months of history).
MIN_DAYS_PER_WEEKDAY = 8
# Descriptive thresholds for "broadly consistent" category distributions.
CONSISTENCY_MAX_TVD = 0.10
CONSISTENCY_MAX_PP_MAJOR = 5.0
MAJOR_CATEGORY_SHARE = 0.05
LOW_EVIDENCE_MINUTES = 30.0
MAPE_MIN_ACTUAL_SEC = 300

REQUIRED_REPORT_COLUMNS = (
    "Report_ID", "Screenshot_Folder", "Summary_Screenshot", "Bars_Screenshot",
    "Capture_Datetime", "Header_Label", "Header_Average", "Week_Start",
    "Date_Mapping_Basis", "Date_Mapping_Status", *WEEKDAYS,
    "Transcription_Method", "Transcription_Status", "Notes",
)
REQUIRED_REFERENCE_COLUMNS = (
    "Date", "Headline_sec", "Category", "Duration_sec", "Source_Screenshots",
    "Use_As_Reference", "Transcription_Status", "Notes",
)

MONTHS = {
    m: i for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)
}


class ReconstructionError(Exception):
    """Raised for invalid inputs or unsafe operations."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$")


def parse_duration_label(label: str) -> int:
    """Parse an Opal label such as '2h 15m', '2h' or '45m' into minutes."""
    match = _DURATION_RE.match(label or "")
    if not match or not any(match.groups()):
        raise ReconstructionError(f"Unparseable Opal duration label: {label!r}")
    hours, minutes = match.groups()
    return int(hours or 0) * 60 + int(minutes or 0)


def parse_header_start(label: str) -> date | None:
    """Return the first date in an Opal header like '7 Sep 2026 – 12 Sep 2026'."""
    match = re.match(r"^\s*(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", label or "")
    if not match or match.group(2) not in MONTHS:
        return None
    return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))


def round_half_up(value: float) -> int:
    """Round to the nearest integer, halves away from zero (no banker's rounding)."""
    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def inclusive_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ReconstructionError(f"End {end} precedes start {start}")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------------------
# Opal reports
# ---------------------------------------------------------------------------

@dataclass
class OpalReport:
    report_id: str
    folder: str
    summary_screenshot: str
    bars_screenshot: str
    capture_datetime: str
    header_label: str
    header_average_min: int
    week_start: date | None
    mapping_basis: str
    mapping_status: str
    bar_labels: tuple[str, ...]
    bar_minutes: tuple[int, ...]
    transcription_method: str
    transcription_status: str
    notes: str
    issues: list[str] = field(default_factory=list)

    @property
    def bar_mean(self) -> float:
        return sum(self.bar_minutes) / 7

    @property
    def header_check_passed(self) -> bool:
        return abs(self.bar_mean - self.header_average_min) <= HEADER_AVERAGE_TOLERANCE_MIN


def validate_report_mapping(report: OpalReport) -> None:
    """Validate the week-to-date mapping; append issues and downgrade status.

    Dates are never inferred from screenshot filename ordering.
    """
    if report.mapping_basis not in MAPPING_BASES:
        report.issues.append(f"Unknown Date_Mapping_Basis {report.mapping_basis!r}")
        report.mapping_status = "UNKNOWN"
    if report.mapping_status not in MAPPING_STATUSES:
        report.issues.append(f"Unknown Date_Mapping_Status {report.mapping_status!r}")
        report.mapping_status = "UNKNOWN"

    if report.week_start is None:
        report.mapping_status = "UNKNOWN"
        report.issues.append("Week_Start not established")
        return

    if report.week_start.weekday() != 0:
        report.issues.append(f"Week_Start {report.week_start} is not a Monday")
        report.mapping_status = "UNKNOWN"
        report.week_start = None
        return

    if report.mapping_basis == "HEADER_LABEL":
        header_start = parse_header_start(report.header_label)
        if header_start != report.week_start:
            report.issues.append(
                f"Header label start {header_start} does not match Week_Start "
                f"{report.week_start}"
            )
            report.mapping_status = "UNKNOWN"
            report.week_start = None
    elif report.mapping_basis == "LAST_WEEK_RELATIVE_TO_CAPTURE":
        try:
            captured = datetime.strptime(report.capture_datetime, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            report.issues.append("Capture_Datetime missing/invalid for relative mapping")
            report.mapping_status = "UNKNOWN"
            report.week_start = None
            return
        expected = monday_of(captured) - timedelta(days=7)
        if expected != report.week_start:
            report.issues.append(
                f"'Last Week' relative to capture {captured} implies {expected}, "
                f"not {report.week_start}"
            )
            report.mapping_status = "UNKNOWN"
            report.week_start = None


def load_opal_reports(path: Path) -> list[OpalReport]:
    """Load and validate the Opal weekly-report transcription file."""
    if not path.exists():
        raise ReconstructionError(f"Opal report file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED_REPORT_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ReconstructionError(f"Opal report file missing columns: {sorted(missing)}")
        rows = list(reader)

    reports: list[OpalReport] = []
    seen: set[str] = set()
    for row in rows:
        report_id = row["Report_ID"].strip()
        if report_id in seen:
            raise ReconstructionError(f"Duplicate Report_ID {report_id}")
        seen.add(report_id)
        labels = tuple(row[d].strip() for d in WEEKDAYS)
        week_start_text = row["Week_Start"].strip()
        report = OpalReport(
            report_id=report_id,
            folder=row["Screenshot_Folder"].strip(),
            summary_screenshot=row["Summary_Screenshot"].strip(),
            bars_screenshot=row["Bars_Screenshot"].strip(),
            capture_datetime=row["Capture_Datetime"].strip(),
            header_label=row["Header_Label"].strip(),
            header_average_min=parse_duration_label(row["Header_Average"]),
            week_start=date.fromisoformat(week_start_text) if week_start_text else None,
            mapping_basis=row["Date_Mapping_Basis"].strip(),
            mapping_status=row["Date_Mapping_Status"].strip().upper(),
            bar_labels=labels,
            bar_minutes=tuple(parse_duration_label(v) for v in labels),
            transcription_method=row["Transcription_Method"].strip(),
            transcription_status=row["Transcription_Status"].strip().upper(),
            notes=row["Notes"].strip(),
        )
        if report.transcription_status not in TRANSCRIPTION_STATUSES:
            report.issues.append(
                f"Unknown Transcription_Status {report.transcription_status!r}"
            )
            report.transcription_status = "PENDING_HUMAN_REVIEW"
        validate_report_mapping(report)
        if not report.header_check_passed:
            report.issues.append(
                f"Seven-bar mean {report.bar_mean:.1f}m differs from header average "
                f"{report.header_average_min}m by more than {HEADER_AVERAGE_TOLERANCE_MIN}m"
            )
        reports.append(report)
    return reports


def discover_opal_screenshots(screenshot_root: Path) -> list[str]:
    """List every image under <month>/Opal folders (relative paths)."""
    found = []
    for folder in sorted(screenshot_root.glob("*/Opal")):
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                found.append(f"{folder.parent.name}/Opal/{path.name}")
    return found


@dataclass(frozen=True)
class OpalDay:
    report_id: str
    date: date | None
    weekday: str
    weekday_index: int
    opal_label: str
    opal_minutes: int
    mapping_status: str
    transcription_status: str
    header_check_passed: bool
    source_screenshot: str

    def review_reasons(self) -> list[str]:
        reasons = []
        if self.mapping_status != "CONFIRMED":
            reasons.append(f"Opal week date mapping {self.mapping_status}")
        if self.transcription_status != "VERIFIED":
            reasons.append("Opal transcription pending human review")
        if not self.header_check_passed:
            reasons.append("Opal bars inconsistent with report header average")
        return reasons


def expand_reports(reports: list[OpalReport]) -> list[OpalDay]:
    """Expand each weekly report into seven Monday->Sunday daily values."""
    days: list[OpalDay] = []
    for report in reports:
        for index, (weekday, label, minutes) in enumerate(
            zip(WEEKDAYS, report.bar_labels, report.bar_minutes)
        ):
            day = report.week_start + timedelta(days=index) if report.week_start else None
            if day is not None and day.weekday() != index:
                raise ReconstructionError(f"Weekday mapping error for {report.report_id}")
            days.append(OpalDay(
                report_id=report.report_id,
                date=day,
                weekday=weekday,
                weekday_index=index,
                opal_label=label,
                opal_minutes=minutes,
                mapping_status=report.mapping_status,
                transcription_status=report.transcription_status,
                header_check_passed=report.header_check_passed,
                source_screenshot=f"{report.folder}/{report.bars_screenshot}",
            ))
    dated = [d.date for d in days if d.date is not None]
    duplicates = sorted({d for d in dated if dated.count(d) > 1})
    if duplicates:
        raise ReconstructionError(
            f"Multiple Opal values for the same date: {[d.isoformat() for d in duplicates]}"
        )
    return days


# ---------------------------------------------------------------------------
# Apple observed data (read-only)
# ---------------------------------------------------------------------------

def apple_daily_path(apple_daily_dir: Path, day: date) -> Path:
    return apple_daily_dir / f"Daily_Time_{day.isoformat()}.csv"


def is_estimated_daily(apple_daily_dir: Path, day: date) -> bool:
    """True when a canonical Daily_Time file is a promoted Opal estimate."""
    path = apple_daily_dir / f"Daily_Time_{day.isoformat()}.metadata.json"
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("evidence_class") == "ESTIMATED"
    except json.JSONDecodeError:
        return False


def has_observed_apple_daily(apple_daily_dir: Path, day: date) -> bool:
    """True only for original Apple observations (never for promoted estimates)."""
    return apple_daily_path(apple_daily_dir, day).exists() and not is_estimated_daily(apple_daily_dir, day)


def _read_daily_rows(apple_daily_dir: Path, day: date) -> list[dict[str, str]] | None:
    """Rows of an OBSERVED canonical Daily_Time file; estimates are never returned."""
    if not has_observed_apple_daily(apple_daily_dir, day):
        return None
    path = apple_daily_path(apple_daily_dir, day)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_apple_daily_seconds(apple_daily_dir: Path, day: date) -> int | None:
    """Return the canonical Apple Daily_Time total in seconds, or None."""
    rows = _read_daily_rows(apple_daily_dir, day)
    if rows is None:
        return None
    return sum(int(row["Duration_sec"]) for row in rows)


def load_apple_headline_seconds(apple_daily_dir: Path, day: date) -> int | None:
    """Return the Apple headline total from Daily_Time metadata (diagnostic only)."""
    path = apple_daily_dir / f"Daily_Time_{day.isoformat()}.metadata.json"
    if not path.exists():
        return None
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["reconciliation"]["headline_seconds"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


@dataclass(frozen=True)
class CategoryDay:
    """Observed Apple category totals for one day (seconds)."""
    date: date
    totals: dict[str, int]          # Daily_Time basis (includes derived residual)
    visible: dict[str, int]         # Apple-visible categories only
    headline_seconds: int | None
    source: str

    @property
    def total(self) -> int:
        return sum(self.totals.values())

    @property
    def visible_total(self) -> int:
        return sum(self.visible.values())


def load_apple_category_day(apple_daily_dir: Path, day: date) -> CategoryDay | None:
    """Category totals from canonical Apple Daily_Time (read-only)."""
    rows = _read_daily_rows(apple_daily_dir, day)
    if rows is None:
        return None
    totals = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
    visible = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
    for row in rows:
        category = row["Category"]
        if category not in totals:
            raise ReconstructionError(
                f"Unexpected Apple category {category!r} in {apple_daily_path(apple_daily_dir, day).name}"
            )
        seconds = int(row["Duration_sec"])
        totals[category] += seconds
        is_residual = (
            row.get("Allocation_Type") == "Derived"
            and row.get("Subcategory") == RESIDUAL_SUBCATEGORY
        )
        if not is_residual:
            visible[category] += seconds
    return CategoryDay(day, totals, visible, load_apple_headline_seconds(apple_daily_dir, day),
                       "CANONICAL_DAILY_TIME")


def load_category_history(apple_daily_dir: Path, start: date, end: date) -> list[CategoryDay]:
    history = []
    for day in inclusive_dates(start, end):
        loaded = load_apple_category_day(apple_daily_dir, day)
        if loaded is not None and loaded.total > 0:
            history.append(loaded)
    return history


@dataclass(frozen=True)
class ReferenceDay:
    date: date
    headline_seconds: int
    visible: dict[str, int]
    use_as_reference: bool
    source: str
    screenshots: str
    notes: str


def load_september_reference(
    path: Path | None, apple_daily_dir: Path, start: date, end: date
) -> list[ReferenceDay]:
    """Observed September Apple data: canonical Daily_Time when present,
    otherwise the screenshot transcription reference (non-canonical)."""
    transcribed: dict[date, ReferenceDay] = {}
    if path is not None and path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(REQUIRED_REFERENCE_COLUMNS) - set(reader.fieldnames or ())
            if missing:
                raise ReconstructionError(f"September reference missing columns: {sorted(missing)}")
            for row in reader:
                day = date.fromisoformat(row["Date"].strip())
                category = row["Category"].strip()
                if category not in APPLE_SCREEN_TIME_CATEGORIES:
                    raise ReconstructionError(f"Unknown category {category!r} in September reference")
                existing = transcribed.get(day)
                if existing is None:
                    existing = ReferenceDay(
                        day, int(row["Headline_sec"]), {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES},
                        row["Use_As_Reference"].strip().upper() == "TRUE",
                        "SCREENSHOT_TRANSCRIPTION_NON_CANONICAL",
                        row["Source_Screenshots"].strip(), row["Notes"].strip(),
                    )
                    transcribed[day] = existing
                elif row["Notes"].strip() and not existing.notes:
                    transcribed[day] = existing = ReferenceDay(
                        existing.date, existing.headline_seconds, existing.visible,
                        existing.use_as_reference, existing.source, existing.screenshots,
                        row["Notes"].strip(),
                    )
                existing.visible[category] += int(row["Duration_sec"])

    reference = []
    for day in inclusive_dates(start, end):
        canonical = load_apple_category_day(apple_daily_dir, day)
        if canonical is not None:
            # A day excluded in the transcription (e.g. phone-setup day) stays excluded.
            flagged = transcribed.get(day)
            excluded = flagged is not None and not flagged.use_as_reference
            reference.append(ReferenceDay(
                day, canonical.headline_seconds or canonical.total, dict(canonical.visible),
                not excluded, "CANONICAL_DAILY_TIME", "", flagged.notes if excluded else "",
            ))
        elif day in transcribed:
            reference.append(transcribed[day])
    return reference


# ---------------------------------------------------------------------------
# Calibration (Opal -> Apple totals)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalibrationPair:
    date: date
    week_start: date
    apple_minutes: float
    opal_minutes: int
    apple_headline_minutes: float | None

    @property
    def difference(self) -> float:
        return self.apple_minutes - self.opal_minutes

    @property
    def ratio(self) -> float:
        return self.opal_minutes / self.apple_minutes if self.apple_minutes else math.nan


def build_calibration_pairs(
    opal_days: list[OpalDay], apple_daily_dir: Path, start: date, end: date,
) -> list[CalibrationPair]:
    """Pair Opal and canonical Apple totals on calibration dates."""
    pairs = []
    for day in opal_days:
        if day.date is None or not (start <= day.date <= end):
            continue
        if day.mapping_status != "CONFIRMED":
            continue
        seconds = load_apple_daily_seconds(apple_daily_dir, day.date)
        if seconds is None:
            continue
        headline = load_apple_headline_seconds(apple_daily_dir, day.date)
        pairs.append(CalibrationPair(
            date=day.date,
            week_start=monday_of(day.date),
            apple_minutes=seconds / 60,
            opal_minutes=day.opal_minutes,
            apple_headline_minutes=headline / 60 if headline is not None else None,
        ))
    return sorted(pairs, key=lambda p: p.date)


def summarize_calibration(pairs: list[CalibrationPair]) -> dict[str, Any]:
    """Compute the calibration statistics from paired daily totals."""
    if len(pairs) < 7:
        raise ReconstructionError(
            f"Calibration needs at least one full week of paired data; got {len(pairs)} days"
        )
    apple = [p.apple_minutes for p in pairs]
    opal = [float(p.opal_minutes) for p in pairs]
    diffs = [p.difference for p in pairs]
    ratios = [p.ratio for p in pairs]
    total_apple = sum(apple)
    total_opal = sum(opal)
    slope, intercept = statistics.linear_regression(opal, apple)

    weeks: dict[date, list[CalibrationPair]] = {}
    for p in pairs:
        weeks.setdefault(p.week_start, []).append(p)
    weekly = [
        {
            "week_start": ws.isoformat(),
            "week_end": (ws + timedelta(days=6)).isoformat(),
            "days": len(items),
            "apple_minutes": round(sum(i.apple_minutes for i in items), 2),
            "opal_minutes": sum(i.opal_minutes for i in items),
            "apple_minus_opal_minutes": round(sum(i.difference for i in items), 2),
            "opal_over_apple": round(
                sum(i.opal_minutes for i in items) / sum(i.apple_minutes for i in items), 4
            ),
        }
        for ws, items in sorted(weeks.items())
    ]

    headline_pairs = [p for p in pairs if p.apple_headline_minutes is not None]
    headline_diff = (
        statistics.fmean(p.apple_headline_minutes - p.opal_minutes for p in headline_pairs)
        if headline_pairs else None
    )

    return {
        "days": len(pairs),
        "first_date": pairs[0].date.isoformat(),
        "last_date": pairs[-1].date.isoformat(),
        "complete_weeks": sum(1 for w in weekly if w["days"] == 7),
        "total_apple_minutes": round(total_apple, 2),
        "total_opal_minutes": round(total_opal, 2),
        "overall_opal_over_apple": total_opal / total_apple,
        "mean_daily_difference_min": statistics.fmean(diffs),
        "median_daily_difference_min": statistics.median(diffs),
        "stdev_daily_difference_min": statistics.stdev(diffs),
        "min_daily_difference_min": min(diffs),
        "max_daily_difference_min": max(diffs),
        "mean_daily_ratio": statistics.fmean(ratios),
        "median_daily_ratio": statistics.median(ratios),
        "correlation_r": statistics.correlation(opal, apple),
        "regression_intercept_min": intercept,
        "regression_slope": slope,
        "weekly": weekly,
        "headline_basis_mean_daily_difference_min": headline_diff,
    }


def fit_models(pairs: list[CalibrationPair]) -> dict[str, dict[str, float]]:
    apple = [p.apple_minutes for p in pairs]
    opal = [float(p.opal_minutes) for p in pairs]
    ratio = sum(opal) / sum(apple)
    slope, intercept = statistics.linear_regression(opal, apple)
    return {
        "A_multiplicative": {"ratio": ratio},
        "B_additive": {"mean_difference": statistics.fmean(a - o for a, o in zip(apple, opal))},
        "C_regression": {"intercept": intercept, "slope": slope},
    }


def predict(model: str, params: dict[str, float], opal_minutes: float) -> float:
    if model == "A_multiplicative":
        return opal_minutes / params["ratio"]
    if model == "B_additive":
        return opal_minutes + params["mean_difference"]
    if model == "C_regression":
        return params["intercept"] + params["slope"] * opal_minutes
    raise ReconstructionError(f"Unknown model {model}")


def _errors(actual: list[float], predicted: list[float]) -> dict[str, float]:
    residuals = [p - a for a, p in zip(actual, predicted)]
    return {
        "mae": statistics.fmean(abs(r) for r in residuals),
        "rmse": math.sqrt(statistics.fmean(r * r for r in residuals)),
        "bias": statistics.fmean(residuals),
    }


def compare_models(pairs: list[CalibrationPair]) -> list[dict[str, Any]]:
    """In-sample and leave-one-week-out errors for each model (diagnostic)."""
    fitted = fit_models(pairs)
    weeks = sorted({p.week_start for p in pairs})
    results = []
    for model, params in fitted.items():
        in_pred = [predict(model, params, p.opal_minutes) for p in pairs]
        in_err = _errors([p.apple_minutes for p in pairs], in_pred)

        cv_actual, cv_pred, weekly_abs = [], [], []
        for held in weeks:
            train = [p for p in pairs if p.week_start != held]
            test = [p for p in pairs if p.week_start == held]
            if len(train) < 2 or not test:
                continue
            train_params = fit_models(train)[model]
            preds = [predict(model, train_params, p.opal_minutes) for p in test]
            cv_actual += [p.apple_minutes for p in test]
            cv_pred += preds
            weekly_abs.append(abs(sum(preds) - sum(p.apple_minutes for p in test)))
        cv_err = (_errors(cv_actual, cv_pred) if cv_actual
                  else {"mae": math.nan, "rmse": math.nan, "bias": math.nan})

        in_weekly = []
        for ws in weeks:
            items = [(p, pr) for p, pr in zip(pairs, in_pred) if p.week_start == ws]
            in_weekly.append(abs(sum(pr for _, pr in items) - sum(p.apple_minutes for p, _ in items)))

        results.append({
            "model": model,
            "parameters": json.dumps({k: round(v, 6) for k, v in params.items()}, sort_keys=True),
            "in_sample_mae_min": in_err["mae"],
            "in_sample_rmse_min": in_err["rmse"],
            "in_sample_mean_abs_weekly_error_min": statistics.fmean(in_weekly),
            "lowo_cv_mae_min": cv_err["mae"],
            "lowo_cv_rmse_min": cv_err["rmse"],
            "lowo_cv_bias_min": cv_err["bias"],
            "lowo_cv_mean_abs_weekly_error_min": statistics.fmean(weekly_abs) if weekly_abs else math.nan,
        })
    return results


def estimate_apple_minutes(opal_minutes: int, calibration_minutes: float) -> int:
    """Additive calibration, rounded half-up to integer minutes (never negative)."""
    return max(0, round_half_up(opal_minutes + calibration_minutes))


# ---------------------------------------------------------------------------
# Category model
# ---------------------------------------------------------------------------

def pooled_shares(days: list[dict[str, int]]) -> dict[str, float]:
    """Time-weighted category shares: sum(category) / sum(total) over days."""
    totals = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
    for day in days:
        for category, seconds in day.items():
            totals[category] += seconds
    grand = sum(totals.values())
    if grand <= 0:
        raise ReconstructionError("Cannot compute category shares from zero observed time")
    return {c: totals[c] / grand for c in APPLE_SCREEN_TIME_CATEGORIES}


def equal_shares() -> dict[str, float]:
    n = len(APPLE_SCREEN_TIME_CATEGORIES)
    return {c: 1 / n for c in APPLE_SCREEN_TIME_CATEGORIES}


def allocate_by_shares(total_seconds: int, shares: dict[str, float]) -> dict[str, int]:
    """Largest-remainder allocation of integer seconds; sums exactly to total.

    Ties are broken by the fixed category order, so results are deterministic.
    """
    weight = sum(shares.get(c, 0.0) for c in APPLE_SCREEN_TIME_CATEGORIES)
    if total_seconds < 0 or weight <= 0:
        raise ReconstructionError("Invalid allocation input")
    raw = {c: total_seconds * shares.get(c, 0.0) / weight for c in APPLE_SCREEN_TIME_CATEGORIES}
    allocated = {c: math.floor(v) for c, v in raw.items()}
    remainder = total_seconds - sum(allocated.values())
    order = sorted(
        APPLE_SCREEN_TIME_CATEGORIES,
        key=lambda c: (-(raw[c] - allocated[c]), APPLE_SCREEN_TIME_CATEGORIES.index(c)),
    )
    for category in order[:remainder]:
        allocated[category] += 1
    return allocated


def weekday_support(history: list[CategoryDay]) -> dict[int, int]:
    counts = {i: 0 for i in range(7)}
    for day in history:
        counts[day.date.weekday()] += 1
    return counts


def shares_for(model: str, history: list[CategoryDay], weekday: int | None,
               exclude: date | None = None) -> dict[str, float]:
    """Category shares for a model, optionally excluding one day (LOO)."""
    if model == MODEL_EQUAL:
        return equal_shares()
    pool = [d for d in history if d.date != exclude]
    if model == MODEL_WEEKDAY:
        pool = [d for d in pool if d.date.weekday() == weekday]
    if not pool:
        raise ReconstructionError(f"No history for {model} (weekday {weekday})")
    return pooled_shares([d.totals for d in pool])


def validate_category_models(history: list[CategoryDay]) -> tuple[list[dict], list[dict]]:
    """Leave-one-day-out retrospective validation on observed history.

    For each observed day, only the daily total is treated as known; categories
    are reconstructed from shares computed without that day.
    """
    per_category, summary = [], []
    for model in (MODEL_EQUAL, MODEL_OVERALL, MODEL_WEEKDAY):
        errors = {c: [] for c in APPLE_SCREEN_TIME_CATEGORIES}
        ape = {c: [] for c in APPLE_SCREEN_TIME_CATEGORIES}
        share_err = {c: [] for c in APPLE_SCREEN_TIME_CATEGORIES}
        agg_pred = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
        agg_actual = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
        misallocated, recon = [], []
        for day in history:
            shares = shares_for(model, history, day.date.weekday(), exclude=day.date)
            predicted = allocate_by_shares(day.total, shares)
            recon.append(abs(sum(predicted.values()) - day.total))
            misallocated.append(sum(abs(predicted[c] - day.totals[c]) for c in predicted) / 2)
            for c in APPLE_SCREEN_TIME_CATEGORIES:
                diff = predicted[c] - day.totals[c]
                errors[c].append(diff / 60)
                share_err[c].append(abs(diff) / day.total * 100)
                agg_pred[c] += predicted[c]
                agg_actual[c] += day.totals[c]
                if day.totals[c] >= MAPE_MIN_ACTUAL_SEC:
                    ape[c].append(abs(diff) / day.totals[c] * 100)
        for c in APPLE_SCREEN_TIME_CATEGORIES:
            per_category.append({
                "Model": model,
                "Category": c,
                "Days": len(errors[c]),
                "Mean_Actual_Min": agg_actual[c] / 60 / len(history),
                "MAE_Min": statistics.fmean(abs(e) for e in errors[c]),
                "RMSE_Min": math.sqrt(statistics.fmean(e * e for e in errors[c])),
                "Bias_Min": statistics.fmean(errors[c]),
                "MAPE_Pct": statistics.fmean(ape[c]) if ape[c] else "",
                "MAPE_Days": len(ape[c]),
                "Mean_Abs_Share_Error_PP": statistics.fmean(share_err[c]),
                "Period_Actual_Min": agg_actual[c] / 60,
                "Period_Predicted_Min": agg_pred[c] / 60,
                "Period_Error_Min": (agg_pred[c] - agg_actual[c]) / 60,
            })
        total_seconds = sum(d.total for d in history)
        summary.append({
            "Model": model,
            "Validation": "Leave-one-day-out",
            "Days": len(history),
            "Mean_Daily_Misallocated_Min": statistics.fmean(misallocated) / 60,
            "Mean_Daily_Misallocated_Pct_Of_Total": sum(misallocated) / total_seconds * 100,
            "Category_MAE_Mean_Min": statistics.fmean(
                r["MAE_Min"] for r in per_category if r["Model"] == model),
            "Category_RMSE_Mean_Min": statistics.fmean(
                r["RMSE_Min"] for r in per_category if r["Model"] == model),
            "Period_Misallocated_Min": sum(
                abs(agg_pred[c] - agg_actual[c]) for c in APPLE_SCREEN_TIME_CATEGORIES) / 2 / 60,
            "Max_Total_Reconciliation_Error_Sec": max(recon),
        })
    return per_category, summary


def select_category_model(history: list[CategoryDay], summary: list[dict]) -> tuple[str, str]:
    """Pre-specified selection rule; returns (model, rationale)."""
    support = weekday_support(history)
    minimum = min(support.values())
    by_model = {s["Model"]: s for s in summary}
    if minimum >= MIN_DAYS_PER_WEEKDAY and (
        by_model[MODEL_WEEKDAY]["Mean_Daily_Misallocated_Min"]
        < by_model[MODEL_OVERALL]["Mean_Daily_Misallocated_Min"]
    ):
        return MODEL_WEEKDAY, (
            f"Every weekday has >= {MIN_DAYS_PER_WEEKDAY} observed days and weekday shares "
            "validate better than overall shares."
        )
    reason = (
        f"Weekday-specific shares not supported: fewest observations per weekday = {minimum} "
        f"(< {MIN_DAYS_PER_WEEKDAY} required)."
        if minimum < MIN_DAYS_PER_WEEKDAY
        else "Weekday-specific shares did not validate better than overall shares."
    )
    return MODEL_OVERALL, reason + " Overall pooled historical shares are used."


def compare_september(history: list[CategoryDay], reference: list[ReferenceDay]) -> dict[str, Any]:
    """Compare August vs observed September category mix (visible basis)."""
    used = [r for r in reference if r.use_as_reference and sum(r.visible.values()) > 0]
    aug_visible = {c: sum(d.visible[c] for d in history) for c in APPLE_SCREEN_TIME_CATEGORIES}
    sep_visible = {c: sum(r.visible[c] for r in used) for c in APPLE_SCREEN_TIME_CATEGORIES}
    aug_total = sum(aug_visible.values())
    sep_total = sum(sep_visible.values())
    rows, tvd, major_pp = [], 0.0, []
    if sep_total <= 0:
        return {"rows": [], "days": 0, "consistent": None, "tvd": None, "max_major_pp": None}
    aug_shares = {c: aug_visible[c] / aug_total for c in APPLE_SCREEN_TIME_CATEGORIES}
    predicted = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
    for r in used:
        alloc = allocate_by_shares(sum(r.visible.values()), aug_shares)
        for c in APPLE_SCREEN_TIME_CATEGORIES:
            predicted[c] += alloc[c]
    for c in APPLE_SCREEN_TIME_CATEGORIES:
        a, s = aug_shares[c], sep_visible[c] / sep_total
        diff = (s - a) * 100
        tvd += abs(s - a) / 2
        if max(a, s) >= MAJOR_CATEGORY_SHARE:
            major_pp.append(abs(diff))
        low = []
        if aug_visible[c] / 60 < LOW_EVIDENCE_MINUTES:
            low.append(f"August < {LOW_EVIDENCE_MINUTES:.0f} min")
        if sep_visible[c] / 60 < LOW_EVIDENCE_MINUTES:
            low.append(f"September < {LOW_EVIDENCE_MINUTES:.0f} min")
        rows.append({
            "Category": c,
            "August_Visible_Min": aug_visible[c] / 60,
            "August_Visible_Share_Pct": a * 100,
            "September_Observed_Min": sep_visible[c] / 60,
            "September_Observed_Share_Pct": s * 100,
            "Share_Difference_PP": diff,
            "Abs_Share_Difference_PP": abs(diff),
            "September_Predicted_From_August_Min": predicted[c] / 60,
            "September_Prediction_Error_Min": (predicted[c] - sep_visible[c]) / 60,
            "Evidence": "LOW_EVIDENCE: " + "; ".join(low) if low else "SUFFICIENT",
        })
    max_major = max(major_pp) if major_pp else 0.0
    return {
        "rows": rows,
        "days": len(used),
        "dates": [r.date.isoformat() for r in used],
        "sources": sorted({r.source for r in used}),
        "excluded": [
            {"date": r.date.isoformat(), "reason": r.notes} for r in reference if not r.use_as_reference
        ],
        "tvd": tvd,
        "max_major_pp": max_major,
        "consistent": tvd <= CONSISTENCY_MAX_TVD and max_major <= CONSISTENCY_MAX_PP_MAJOR,
        "august_visible_minutes": aug_total / 60,
        "september_visible_minutes": sep_total / 60,
    }


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

def reconstruct(
    missing_dates: list[date],
    opal_days: list[OpalDay],
    calibration_minutes: float,
    calibration_status: str,
    apple_daily_dir: Path,
    category_model: str,
) -> list[dict[str, Any]]:
    """Return one daily reconstruction record per missing date."""
    by_date = {d.date: d for d in opal_days if d.date is not None}
    records = []
    for day in missing_dates:
        opal = by_date.get(day)
        record: dict[str, Any] = {
            "Date": day.isoformat(),
            "Weekday": WEEKDAYS[day.weekday()],
            "Opal_Available": opal is not None,
            "Opal_Report_ID": opal.report_id if opal else "",
            "Opal_Source_Screenshot": opal.source_screenshot if opal else "",
            "Opal_Label": opal.opal_label if opal else "",
            "Opal_Minutes": opal.opal_minutes if opal else "",
            "Opal_Date_Mapping_Status": opal.mapping_status if opal else "",
            "Opal_Transcription_Status": opal.transcription_status if opal else "",
            "Calibration_Method": "Additive",
            "Calibration_Minutes": round(calibration_minutes, 4),
            "Calibration_Version": METHOD_VERSION,
            "Calibration_Status": calibration_status,
            "Estimated_Apple_Minutes": "",
            "Estimated_Apple_Seconds": "",
            "Category_Model": "",
            "Estimate_Status": "",
            "Source_Detail": SOURCE_DETAIL,
            "Allocation_Type": ALLOCATION_TYPE,
            "Evidence_Type": EVIDENCE_TYPE,
            "Evidence_Source": EVIDENCE_SOURCE,
            "Evidence_Quality": EVIDENCE_QUALITY,
            "Review_Status": "",
            "Review_Reasons": "",
        }
        if has_observed_apple_daily(apple_daily_dir, day):
            # Never replace an original Apple observation.
            record.update(
                Allocation_Type="",
                Estimate_Status="SKIPPED_OBSERVED_APPLE_EXISTS",
                Review_Status="REVIEW",
                Review_Reasons="Observed Apple Daily_Time exists for a date listed as missing",
            )
        elif opal is None:
            record.update(
                Allocation_Type="",
                Estimate_Status="NO_OPAL_EVIDENCE",
                Review_Status="REVIEW",
                Review_Reasons="No Opal daily value for this date; not estimated (no zero created)",
            )
        else:
            minutes = estimate_apple_minutes(opal.opal_minutes, calibration_minutes)
            reasons = opal.review_reasons()
            if calibration_status != "FINAL":
                reasons.append(f"Calibration {calibration_status}")
            record.update(
                Estimated_Apple_Minutes=minutes,
                Estimated_Apple_Seconds=minutes * 60,
                Category_Model=category_model,
                Estimate_Status="ESTIMATED",
                Review_Status="REVIEW" if reasons else "READY",
                Review_Reasons="; ".join(reasons),
            )
        records.append(record)
    return records


def category_rows(
    records: list[dict[str, Any]],
    history: list[CategoryDay],
    category_model: str,
    history_label: str,
    validation_label: str,
) -> list[dict[str, Any]]:
    """Daily_Time-compatible category allocation rows for estimated dates."""
    rows = []
    for record in records:
        if record["Estimate_Status"] != "ESTIMATED":
            continue
        day = date.fromisoformat(record["Date"])
        shares = shares_for(category_model, history, day.weekday())
        allocation = allocate_by_shares(int(record["Estimated_Apple_Seconds"]), shares)
        for category in APPLE_SCREEN_TIME_CATEGORIES:
            rows.append({
                "Date": record["Date"],
                "Source": SOURCE,
                "Category": category,
                "Subcategory": category,
                "Duration_sec": allocation[category],
                "Event_Count": 0,
                "Allocation_Type": ALLOCATION_TYPE,
                "Evidence_Type": EVIDENCE_TYPE,
                "Evidence_Source": EVIDENCE_SOURCE,
                "Source_Detail": SOURCE_DETAIL,
                "Estimation_Method": ESTIMATION_METHOD,
                "Category_Allocation": CATEGORY_ALLOCATION,
                "Category_Model": category_model,
                "Category_Share": round(shares[category], 8),
                "Category_History": history_label,
                "Current_Period_Validation": validation_label,
                "Calibration_Version": METHOD_VERSION,
                "Opal_Report_ID": record["Opal_Report_ID"],
                "Review_Status": record["Review_Status"],
            })
    return rows


def overlap_validation(
    opal_days: list[OpalDay],
    apple_daily_dir: Path,
    reference: list[ReferenceDay],
    excluded_dates: set[date],
    calibration_minutes: float,
) -> list[dict[str, Any]]:
    """Out-of-sample check on Opal dates outside calibration and the missing period."""
    ref_by_date = {r.date: r for r in reference}
    rows = []
    for day in opal_days:
        if day.date is None or day.date in excluded_dates:
            continue
        estimate = estimate_apple_minutes(day.opal_minutes, calibration_minutes)
        canonical = load_apple_daily_seconds(apple_daily_dir, day.date)
        ref = ref_by_date.get(day.date)
        if canonical is not None:
            observed, source, status = canonical / 60, "CANONICAL_DAILY_TIME", "COMPARED"
        elif ref is not None:
            observed, source = ref.headline_seconds / 60, ref.source + "_HEADLINE"
            status = "COMPARED" if ref.use_as_reference else "COMPARED_FLAGGED"
        else:
            observed, source, status = None, "", "PENDING_APPLE_NOT_AVAILABLE"
        rows.append({
            "Date": day.date.isoformat(),
            "Weekday": day.weekday,
            "Opal_Report_ID": day.report_id,
            "Opal_Minutes": day.opal_minutes,
            "Estimated_Apple_Minutes": estimate,
            "Observed_Apple_Minutes": round(observed, 2) if observed is not None else "",
            "Estimation_Error_Min": round(estimate - observed, 2) if observed is not None else "",
            "Observed_Source": source,
            "Status": status,
            "Notes": (ref.notes if ref is not None and not ref.use_as_reference else ""),
        })
    return sorted(rows, key=lambda r: r["Date"])


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.4f}"
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    columns = columns or (list(rows[0].keys()) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _fmt(row.get(k, "")) for k in columns})


def ensure_safe_output_dir(output_dir: Path, force: bool) -> None:
    """Refuse canonical trees; with --force, clear only this layer's own files."""
    resolved = output_dir.resolve()
    for protected in PROTECTED_OUTPUT_ROOTS:
        if resolved == protected.resolve() or protected.resolve() in resolved.parents:
            raise ReconstructionError(
                f"Refusing to write reconstruction output into canonical tree {protected}"
            )
    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise ReconstructionError(
                f"Output directory already contains files: {output_dir}. Use --force to regenerate."
            )
        for path in output_dir.iterdir():
            if path.is_file():
                path.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def hm(minutes: float) -> str:
    total = round_half_up(minutes)
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 60}h {total % 60:02d}m"


def methodology_report(ctx: dict[str, Any]) -> str:
    cal = ctx["calibration"]
    est = [r for r in ctx["records"] if r["Estimate_Status"] == "ESTIMATED"]
    review = [r for r in ctx["records"] if r["Review_Status"] == "REVIEW"]
    no_opal = [r["Date"] for r in ctx["records"] if r["Estimate_Status"] == "NO_OPAL_EVIDENCE"]
    sep = ctx["september"]
    val = {s["Model"]: s for s in ctx["category_summary"]}
    shares = ctx["selected_shares"]
    lines = [
        "# Apple Screen Time Reconstruction from Opal — Methodology",
        "",
        f"Method version: `{METHOD_VERSION}`  ",
        f"Missing Apple period: {ctx['missing_start']} .. {ctx['missing_end']}  ",
        f"Total calibration: {cal['first_date']} .. {cal['last_date']} "
        f"({cal['days']} paired days, {cal['complete_weeks']} complete weeks) — status **{ctx['calibration_status']}**  ",
        f"Category history: {ctx['history_label']}  ",
        f"Category model: **{ctx['category_model']}**",
        "",
        "## Commentary for the September analysis",
        "",
        (
            f"The original Apple Screen Time evidence for {ctx['missing_start']} through "
            f"{ctx['missing_end']} was unavailable following an iPhone replacement. Opal weekly "
            "reports were retained and used as a secondary screen-time source. August 2026 "
            "provides an empirical calibration period where both Apple Screen Time and Opal are "
            f"available: across {cal['complete_weeks']} complete August weeks Opal recorded "
            f"{cal['overall_opal_over_apple'] * 100:.1f}% of Apple Screen Time and undercounted it by "
            f"{cal['mean_daily_difference_min']:.1f} minutes per day on average (daily r = "
            f"{cal['correlation_r']:.3f}). Missing September Apple totals are reconstructed from Opal "
            f"by adding this empirically derived August difference ({len(est)} dates, "
            f"{hm(sum(int(r['Estimated_Apple_Minutes']) for r in est))} in total). Category-level "
            "values are not directly observed for the missing period and are therefore estimated "
            "using the historical Apple Screen Time category distribution observed in August 2026 "
            f"({ctx['category_model_text']}). Observed September Apple data is preserved separately "
            "and is used as a current-period validation reference where available"
            + (
                f" ({sep['days']} days; distribution {'broadly consistent' if sep['consistent'] else 'NOT broadly consistent'} "
                f"with August, total variation distance {sep['tvd'] * 100:.1f} pp)."
                if sep.get("days") else "."
            )
            + " Reconstructed values must not be interpreted as original Apple Screen Time observations."
        ),
        "",
        "## 1. Total calibration (canonical August Apple Daily_Time vs Opal)",
        "",
        f"- Apple total: {cal['total_apple_minutes']:.1f} min ({hm(cal['total_apple_minutes'])})",
        f"- Opal total: {cal['total_opal_minutes']:.0f} min ({hm(cal['total_opal_minutes'])})",
        f"- Opal / Apple (overall): {cal['overall_opal_over_apple']:.4f}",
        f"- Mean daily Apple − Opal: {cal['mean_daily_difference_min']:.2f} min "
        f"(median {cal['median_daily_difference_min']:.2f}, sd {cal['stdev_daily_difference_min']:.2f}, "
        f"range {cal['min_daily_difference_min']:.1f} .. {cal['max_daily_difference_min']:.1f})",
        f"- Mean / median daily Opal / Apple: {cal['mean_daily_ratio']:.4f} / {cal['median_daily_ratio']:.4f}",
        f"- Daily correlation r: {cal['correlation_r']:.4f}",
        f"- OLS Apple = {cal['regression_intercept_min']:.2f} + {cal['regression_slope']:.4f} × Opal",
        "",
        "| Week | Apple | Opal | Apple − Opal | Opal/Apple |",
        "|---|---:|---:|---:|---:|",
    ]
    for w in cal["weekly"]:
        lines.append(
            f"| {w['week_start']} .. {w['week_end']} | {hm(w['apple_minutes'])} | "
            f"{hm(w['opal_minutes'])} | {hm(w['apple_minus_opal_minutes'])} | {w['opal_over_apple']:.3f} |"
        )
    lines += [
        "",
        "Total-model comparison (diagnostic; additive was pre-specified):",
        "",
        "| Model | In-sample MAE | In-sample RMSE | LOWO-CV MAE | LOWO-CV RMSE |",
        "|---|---:|---:|---:|---:|",
    ]
    for m in ctx["models"]:
        lines.append(
            f"| {m['model']} | {m['in_sample_mae_min']:.1f} | {m['in_sample_rmse_min']:.1f} | "
            f"{m['lowo_cv_mae_min']:.1f} | {m['lowo_cv_rmse_min']:.1f} |"
        )
    lines += [
        "",
        f"Rule: `Estimated_Apple_Minutes = round_half_up(Opal_Minutes + {cal['mean_daily_difference_min']:.4f})`.",
        "The constant is recomputed from the paired August data on every run.",
        "",
        "## 2. Category allocation",
        "",
        "Category proportions are pooled (time-weighted) shares of canonical August Apple Daily_Time,",
        "on the same basis as the calibrated totals: the builder-derived residual (Apple headline minus",
        f"visible categories, stored as Utilities / {RESIDUAL_SUBCATEGORY}) stays in Utilities.",
        "",
        "| Category | Share used |",
        "|---|---:|",
    ]
    for c in APPLE_SCREEN_TIME_CATEGORIES:
        lines.append(f"| {c} | {shares[c] * 100:.2f}% |")
    lines += [
        "",
        f"Selection rule (pre-specified): weekday-specific shares only if every weekday has ≥ "
        f"{MIN_DAYS_PER_WEEKDAY} observed days and they validate better than overall shares. "
        f"{ctx['selection_reason']}",
        "",
        "Retrospective validation (leave-one-day-out on August; only the daily total is treated as known):",
        "",
        "| Model | Mean daily misallocated | % of daily total | Mean category MAE | Period misallocated |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in (MODEL_EQUAL, MODEL_OVERALL, MODEL_WEEKDAY):
        s = val[model]
        lines.append(
            f"| {model} | {s['Mean_Daily_Misallocated_Min']:.1f} min | "
            f"{s['Mean_Daily_Misallocated_Pct_Of_Total']:.1f}% | {s['Category_MAE_Mean_Min']:.1f} min | "
            f"{s['Period_Misallocated_Min']:.1f} min |"
        )
    lines += [
        "",
        "Allocation is integer seconds by largest remainder (ties in fixed category order), so the",
        "categories of every reconstructed day sum exactly to its estimated total. No app-level rows",
        "are created. Daily category values carry the uncertainty shown above; the period-level",
        "category mix is much more reliable than any single day.",
        "",
        "Combined August + September proportions (Model C) are not used: the September reference is",
        "a short window from a newly set-up phone, it is on the visible-category basis only (no",
        "residual), and — where it is a screenshot transcription — it is not canonical data.",
        "",
        "## 3. August vs observed September (visible-category basis)",
        "",
    ]
    if sep.get("days"):
        lines += [
            f"September reference days: {sep['days']} ({', '.join(sep['dates'])}); sources: "
            f"{', '.join(sep['sources'])}.",
            f"Total variation distance: {sep['tvd'] * 100:.1f} pp; largest difference among major "
            f"categories (≥ {MAJOR_CATEGORY_SHARE * 100:.0f}% share): {sep['max_major_pp']:.1f} pp → "
            f"**{'broadly consistent' if sep['consistent'] else 'not broadly consistent'}** "
            f"(thresholds: TVD ≤ {CONSISTENCY_MAX_TVD * 100:.0f} pp and major-category difference ≤ "
            f"{CONSISTENCY_MAX_PP_MAJOR:.0f} pp).",
            "",
            "| Category | August share | September share | Difference (pp) | Evidence |",
            "|---|---:|---:|---:|---|",
        ]
        for r in sep["rows"]:
            lines.append(
                f"| {r['Category']} | {r['August_Visible_Share_Pct']:.2f}% | "
                f"{r['September_Observed_Share_Pct']:.2f}% | {r['Share_Difference_PP']:+.2f} | {r['Evidence']} |"
            )
        for item in sep["excluded"]:
            lines.append(f"\nExcluded from reference: {item['date']} — {item['reason']}")
    else:
        lines.append("No observed September Apple category data available.")
    lines += [
        "",
        "## 4. Coverage and review",
        "",
        f"- Missing-period dates: {len(ctx['records'])}",
        f"- Estimated: {len(est)}  (total {sum(int(r['Estimated_Apple_Minutes']) for r in est)} min)",
        f"- No Opal evidence: {len(no_opal)} — {', '.join(no_opal) if no_opal else 'none'}",
        f"- REVIEW dates: {len(review)}",
        "",
        "## 5. Known caveats",
        "",
        "- Total calibration rests on 4 weeks (28 days); daily differences vary (see sd and range).",
        "- Opal bar labels are rounded (observed steps of 5 and 15 minutes).",
        "- Opal headers show Monday – Saturday while seven bars are drawn; the header average equals",
        "  the seven-bar mean and is checked for every report.",
        "- On days where visible Apple categories exceeded the headline, Daily_Time follows categories;",
        "  the headline-basis mean difference is "
        + (f"{cal['headline_basis_mean_daily_difference_min']:.2f} min (diagnostic)."
           if cal["headline_basis_mean_daily_difference_min"] is not None else "unavailable."),
        "- Opal transcriptions were made from screenshots; their verification method is recorded per",
        "  report in Opal_Weekly_Reports.csv.",
        "",
    ]
    return "\n".join(lines)


def provenance_report(ctx: dict[str, Any]) -> str:
    lines = [
        "# Apple Screen Time Reconstruction — Provenance",
        "",
        "## Evidence classes",
        "",
        "| Class | Data | Status |",
        "|---|---|---|",
        "| OBSERVED | Canonical August Apple Screen Time (Raw/Fact/Daily) | Read only; byte-identical |",
        "| OBSERVED | September Apple Screen Time surviving the phone replacement | Read only; validation reference |",
        "| OBSERVED | Original Opal screenshots | Read only; SHA-256 in audit trail |",
        "| ESTIMATED | Reconstructed September daily totals | This directory only |",
        "| ESTIMATED | Reconstructed September category values | This directory only |",
        "",
        "## Field values on reconstructed records",
        "",
        "Existing System Tracker Daily_Time fields:",
        "",
        f"- `Source`: `{SOURCE}` (unchanged device source key)",
        f"- `Allocation_Type`: `{ALLOCATION_TYPE}` (observed Apple rows use Observed / Derived / Mixed)",
        f"- `Evidence_Type`: `{EVIDENCE_TYPE}`",
        f"- `Evidence_Source`: `{EVIDENCE_SOURCE}`",
        f"- `Event_Count`: `0` (no events were observed)",
        "",
        "Reconstruction-only fields (no existing equivalent):",
        "",
        f"- `Source_Detail`: `{SOURCE_DETAIL}`",
        f"- `Estimation_Method`: `{ESTIMATION_METHOD}`",
        f"- `Category_Allocation`: `{CATEGORY_ALLOCATION}`",
        f"- `Category_Model`: `{ctx['category_model']}`",
        "- `Category_Share`: share applied to the day's estimated total",
        f"- `Category_History`: `{ctx['history_label']}`",
        f"- `Current_Period_Validation`: `{ctx['validation_label']}`",
        f"- `Calibration_Version`: `{METHOD_VERSION}`",
        "- `Opal_Report_ID`: the Opal weekly report the day's value came from",
        "- `Review_Status`: READY or REVIEW",
        "",
        "## Inputs",
        "",
        "- Opal transcription: `input/iPhone/Opal/Opal_Weekly_Reports.csv`",
        "- Opal screenshots: `input/iPhone/ScreenTime/<month>/Opal/` (original filenames preserved)",
        "- Calibration and category history: `output/Daily/Time/AppleScreenTime/iPhone/Daily_Time_2026-08-*.csv`",
        "- September reference: canonical Daily_Time when available, otherwise "
        "`input/iPhone/Reconstruction/Apple_September_Observed_Reference.csv` (screenshot transcription, non-canonical)",
        "",
        "Checksums of every input and output are in `14_Audit_Trail.json`.",
        "",
    ]
    return "\n".join(lines)


def run(
    *,
    opal_reports_path: Path,
    screenshot_root: Path,
    apple_daily_dir: Path,
    output_dir: Path,
    missing_start: date,
    missing_end: date,
    calibration_start: date,
    calibration_end: date,
    history_start: date,
    history_end: date,
    september_reference_path: Path | None,
    reference_start: date,
    reference_end: date,
    force: bool = False,
    check_screenshots: bool = True,
) -> dict[str, Any]:
    """Run the full reconstruction and write all outputs. Returns a summary."""
    reports = load_opal_reports(opal_reports_path)
    opal_days = expand_reports(reports)

    screenshot_hashes: dict[str, str] = {}
    untranscribed: list[str] = []
    if check_screenshots:
        referenced = set()
        for report in reports:
            for name in (report.summary_screenshot, report.bars_screenshot):
                rel = f"{report.folder}/{name}"
                path = screenshot_root / rel
                if not path.exists():
                    raise ReconstructionError(f"Opal screenshot not found: {path}")
                screenshot_hashes[rel] = sha256_file(path)
                referenced.add(rel)
        untranscribed = [p for p in discover_opal_screenshots(screenshot_root) if p not in referenced]

    # Totals calibration ------------------------------------------------------
    pairs = build_calibration_pairs(opal_days, apple_daily_dir, calibration_start, calibration_end)
    calibration = summarize_calibration(pairs)
    models = compare_models(pairs)
    calibration_dates = {p.date for p in pairs}
    calibration_reports = {d.report_id for d in opal_days if d.date in calibration_dates}
    calibration_status = (
        "FINAL"
        if all(r.transcription_status == "VERIFIED" and r.header_check_passed
               for r in reports if r.report_id in calibration_reports)
        else "PROVISIONAL_PENDING_TRANSCRIPTION_REVIEW"
    )
    calibration_minutes = calibration["mean_daily_difference_min"]

    # Category model ------------------------------------------------------------
    history = load_category_history(apple_daily_dir, history_start, history_end)
    if len(history) < 7:
        raise ReconstructionError(f"Category history needs at least 7 observed days; got {len(history)}")
    category_validation, category_summary = validate_category_models(history)
    category_model, selection_reason = select_category_model(history, category_summary)
    history_label = (
        f"{history_start.strftime('%B %Y')} observed Apple Screen Time "
        f"({history[0].date.isoformat()}..{history[-1].date.isoformat()}, {len(history)} days)"
    )
    reference = load_september_reference(
        september_reference_path, apple_daily_dir, reference_start, reference_end)
    september = compare_september(history, reference)
    validation_label = (
        "Observed September Apple Screen Time where available ("
        + (", ".join(september["sources"]) + f"; {september['days']} days" if september.get("days") else "none")
        + ")"
    )
    selected_shares = shares_for(category_model, history, None) if category_model != MODEL_WEEKDAY else None

    # Reconstruction -------------------------------------------------------------
    missing_dates = inclusive_dates(missing_start, missing_end)
    records = reconstruct(missing_dates, opal_days, calibration_minutes, calibration_status,
                          apple_daily_dir, category_model)
    allocation = category_rows(records, history, category_model, history_label, validation_label)
    overlap = overlap_validation(
        opal_days, apple_daily_dir, reference, calibration_dates | set(missing_dates), calibration_minutes)

    for record in records:
        if record["Estimate_Status"] == "ESTIMATED":
            allocated = sum(r["Duration_sec"] for r in allocation if r["Date"] == record["Date"])
            if allocated != record["Estimated_Apple_Seconds"]:
                raise ReconstructionError(f"Allocation does not reconcile for {record['Date']}")

    ensure_safe_output_dir(output_dir, force)

    params = fit_models(pairs)
    calibration_rows = []
    for p in pairs:
        row = {
            "Date": p.date.isoformat(),
            "Weekday": WEEKDAYS[p.date.weekday()],
            "Week_Start": p.week_start.isoformat(),
            "Apple_Observed_Minutes": round(p.apple_minutes, 2),
            "Apple_Headline_Minutes": round(p.apple_headline_minutes, 2) if p.apple_headline_minutes is not None else "",
            "Opal_Minutes": p.opal_minutes,
            "Apple_Minus_Opal_Min": round(p.difference, 2),
            "Opal_Over_Apple": round(p.ratio, 4),
        }
        for model, short in (("A_multiplicative", "Mult"), ("B_additive", "Add"), ("C_regression", "Reg")):
            estimate = predict(model, params[model], p.opal_minutes)
            row[f"Est_Apple_{short}_Min"] = round(estimate, 2)
            row[f"Error_{short}_Min"] = round(estimate - p.apple_minutes, 2)
        calibration_rows.append(row)

    extraction_rows = [
        {
            "Report_ID": d.report_id,
            "Date": d.date.isoformat() if d.date else "",
            "Weekday": d.weekday,
            "Weekday_Index": d.weekday_index,
            "Opal_Label": d.opal_label,
            "Opal_Minutes": d.opal_minutes,
            "Estimated_Apple_Minutes": estimate_apple_minutes(d.opal_minutes, calibration_minutes),
            "Use": (
                "CALIBRATION" if d.date in calibration_dates
                else "RECONSTRUCTION" if d.date in set(missing_dates)
                else "OVERLAP_VALIDATION" if d.date is not None else "UNMAPPED"
            ),
            "Date_Mapping_Status": d.mapping_status,
            "Transcription_Status": d.transcription_status,
            "Header_Check_Passed": d.header_check_passed,
            "Source_Screenshot": d.source_screenshot,
        }
        for d in opal_days
    ]
    report_rows = [
        {
            "Report_ID": r.report_id,
            "Summary_Screenshot": f"{r.folder}/{r.summary_screenshot}",
            "Bars_Screenshot": f"{r.folder}/{r.bars_screenshot}",
            "Capture_Datetime": r.capture_datetime,
            "Header_Label": r.header_label,
            "Week_Start": r.week_start.isoformat() if r.week_start else "",
            "Week_End": (r.week_start + timedelta(days=6)).isoformat() if r.week_start else "",
            "Date_Mapping_Basis": r.mapping_basis,
            "Date_Mapping_Status": r.mapping_status,
            "Header_Average_Min": r.header_average_min,
            "Bar_Mean_Min": round(r.bar_mean, 2),
            "Bar_Total_Min": sum(r.bar_minutes),
            "Header_Check_Passed": r.header_check_passed,
            "Transcription_Status": r.transcription_status,
            "Issues": "; ".join(r.issues),
        }
        for r in reports
    ]

    hist_total = sum(d.total for d in history)
    hist_visible = sum(d.visible_total for d in history)
    distribution_rows = []
    for c in APPLE_SCREEN_TIME_CATEGORIES:
        total_c = sum(d.totals[c] for d in history)
        visible_c = sum(d.visible[c] for d in history)
        distribution_rows.append({
            "Category": c,
            "Days_With_Use": sum(1 for d in history if d.totals[c] > 0),
            "Total_Min": total_c / 60,
            "Share_Pct": total_c / hist_total * 100,
            "Visible_Min": visible_c / 60,
            "Visible_Share_Pct": visible_c / hist_visible * 100,
            "Derived_Residual_Min": (total_c - visible_c) / 60,
            "Share_Used_Pct": selected_shares[c] * 100 if selected_shares else "",
        })
    coverage_history_rows = [
        {
            "Date": d.date.isoformat(),
            "Weekday": WEEKDAYS[d.date.weekday()],
            "Daily_Time_Min": d.total / 60,
            "Headline_Min": d.headline_seconds / 60 if d.headline_seconds is not None else "",
            "Visible_Category_Min": d.visible_total / 60,
            "Derived_Residual_Min": (d.total - d.visible_total) / 60,
            "Categories_Present": sum(1 for v in d.totals.values() if v > 0),
            "Daily_Time_Equals_Headline": (
                d.headline_seconds is not None and abs(d.total - d.headline_seconds) <= 60
            ),
        }
        for d in history
    ]
    support = weekday_support(history)
    weekday_rows = []
    for wd in range(7):
        pool = [d for d in history if d.date.weekday() == wd]
        if not pool:
            continue
        shares = pooled_shares([d.totals for d in pool])
        for c in APPLE_SCREEN_TIME_CATEGORIES:
            weekday_rows.append({
                "Weekday": WEEKDAYS[wd],
                "Observed_Days": support[wd],
                "Supported": support[wd] >= MIN_DAYS_PER_WEEKDAY,
                "Category": c,
                "Total_Min": sum(d.totals[c] for d in pool) / 60,
                "Share_Pct": shares[c] * 100,
                "Days_With_Use": sum(1 for d in pool if d.totals[c] > 0),
            })

    coverage_rows = [
        {
            "Date": r["Date"],
            "Weekday": r["Weekday"],
            "Opal_Available": r["Opal_Available"],
            "Opal_Minutes": r["Opal_Minutes"],
            "Estimated_Apple_Minutes": r["Estimated_Apple_Minutes"],
            "Category_Model": r["Category_Model"],
            "Status": r["Estimate_Status"],
            "Review_Status": r["Review_Status"],
            "Evidence_Source": (
                f"{r['Opal_Source_Screenshot']} ({r['Opal_Report_ID']})" if r["Opal_Available"] else ""
            ),
            "Observed_Apple_Daily": has_observed_apple_daily(apple_daily_dir, date.fromisoformat(r["Date"])),
            "Review_Reasons": r["Review_Reasons"],
        }
        for r in records
    ]

    summary_cal = {k: v for k, v in calibration.items() if k != "weekly"}
    outputs = {
        "01_August_Calibration_Daily.csv": calibration_rows,
        "01_August_Calibration_Weekly.csv": calibration["weekly"],
        "02_Calibration_Model_Comparison.csv": models,
        "03_Opal_Weekly_Reports.csv": report_rows,
        "03_Opal_Daily_Extraction.csv": extraction_rows,
        "04_Reconstructed_Daily_Totals.csv": records,
        "05_Reconstructed_Category_Allocation.csv": allocation,
        "06_Historical_Category_Distribution.csv": distribution_rows,
        "06_Historical_Category_Coverage.csv": coverage_history_rows,
        "07_Weekday_Category_Distribution.csv": weekday_rows,
        "08_Category_Model_Validation.csv": category_validation,
        "08_Category_Model_Validation_Summary.csv": category_summary,
        "09_September_Category_Comparison.csv": september["rows"],
        "10_Coverage_Report.csv": coverage_rows,
        "11_Overlap_Validation.csv": overlap,
    }
    for name, rows in outputs.items():
        write_csv(output_dir / name, rows)

    estimated = [r for r in records if r["Estimate_Status"] == "ESTIMATED"]
    category_totals = {c: 0 for c in APPLE_SCREEN_TIME_CATEGORIES}
    for row in allocation:
        category_totals[row["Category"]] += row["Duration_sec"]

    calibration_summary = {
        "calibration": summary_cal,
        "calibration_status": calibration_status,
        "category_model": category_model,
        "category_selection_reason": selection_reason,
        "september_comparison": {k: v for k, v in september.items() if k != "rows"},
    }
    (output_dir / "01_Calibration_Summary.json").write_text(
        json.dumps(calibration_summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    model_text = (
        "overall pooled August shares" if category_model == MODEL_OVERALL
        else "weekday-specific pooled August shares"
    )
    ctx = {
        "calibration": calibration, "models": models, "records": records,
        "missing_start": missing_start.isoformat(), "missing_end": missing_end.isoformat(),
        "calibration_status": calibration_status, "category_model": category_model,
        "category_model_text": model_text, "selection_reason": selection_reason,
        "category_summary": category_summary, "september": september,
        "selected_shares": selected_shares or equal_shares(),
        "history_label": history_label, "validation_label": validation_label,
    }
    (output_dir / "12_Methodology_Report.md").write_text(methodology_report(ctx), encoding="utf-8")
    (output_dir / "13_Provenance_Report.md").write_text(provenance_report(ctx), encoding="utf-8")

    summary = {
        "method_version": METHOD_VERSION,
        "missing_period": [missing_start.isoformat(), missing_end.isoformat()],
        "calibration_period": [calibration_start.isoformat(), calibration_end.isoformat()],
        "calibration_status": calibration_status,
        "calibration_minutes": calibration_minutes,
        "category_model": category_model,
        "category_selection_reason": selection_reason,
        "estimated_dates": [r["Date"] for r in estimated],
        "review_dates": [r["Date"] for r in records if r["Review_Status"] == "REVIEW"],
        "no_opal_dates": [r["Date"] for r in records if r["Estimate_Status"] == "NO_OPAL_EVIDENCE"],
        "skipped_observed_dates": [
            r["Date"] for r in records if r["Estimate_Status"] == "SKIPPED_OBSERVED_APPLE_EXISTS"
        ],
        "estimated_total_minutes": sum(int(r["Estimated_Apple_Minutes"]) for r in estimated),
        "estimated_total_opal_minutes": sum(int(r["Opal_Minutes"]) for r in estimated),
        "estimated_category_minutes": {c: category_totals[c] / 60 for c in APPLE_SCREEN_TIME_CATEGORIES},
        "opal_screenshots_discovered": len(discover_opal_screenshots(screenshot_root)) if check_screenshots else None,
        "opal_screenshots_untranscribed": untranscribed,
        "opal_reports": len(reports),
        "opal_report_issues": {r.report_id: r.issues for r in reports if r.issues},
    }
    audit = {
        "summary": summary,
        "constants": {
            "source": SOURCE, "source_detail": SOURCE_DETAIL,
            "allocation_type": ALLOCATION_TYPE, "evidence_type": EVIDENCE_TYPE,
            "evidence_source": EVIDENCE_SOURCE, "estimation_method": ESTIMATION_METHOD,
            "category_allocation": CATEGORY_ALLOCATION,
            "categories": list(APPLE_SCREEN_TIME_CATEGORIES),
            "header_average_tolerance_min": HEADER_AVERAGE_TOLERANCE_MIN,
            "min_days_per_weekday": MIN_DAYS_PER_WEEKDAY,
            "consistency_max_tvd": CONSISTENCY_MAX_TVD,
            "consistency_max_pp_major": CONSISTENCY_MAX_PP_MAJOR,
        },
        "inputs": {
            "opal_reports_csv": {"path": opal_reports_path.name, "sha256": sha256_file(opal_reports_path)},
            "september_reference_csv": (
                {"path": september_reference_path.name, "sha256": sha256_file(september_reference_path)}
                if september_reference_path is not None and september_reference_path.exists() else None
            ),
            "opal_screenshots_sha256": dict(sorted(screenshot_hashes.items())),
            "apple_daily_files_sha256": {
                apple_daily_path(apple_daily_dir, d).name: sha256_file(apple_daily_path(apple_daily_dir, d))
                for d in sorted({p.date for p in pairs} | {h.date for h in history})
            },
        },
        "outputs_sha256": {
            path.name: sha256_file(path)
            for path in sorted(output_dir.iterdir())
            if path.is_file() and path.name != "14_Audit_Trail.json"
        },
    }
    (output_dir / "14_Audit_Trail.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary["calibration"] = summary_cal
    summary["models"] = models
    summary["category_summary"] = category_summary
    summary["september"] = september
    summary["selected_shares"] = selected_shares
    summary["output_dir"] = str(output_dir)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct missing Apple Screen Time totals and categories from Opal weekly "
                    "reports (estimation layer; does not modify canonical Apple data)."
    )
    parser.add_argument("--missing-start", default="2026-09-01")
    parser.add_argument("--missing-end", default="2026-09-22")
    parser.add_argument("--calibration-start", default="2026-08-03")
    parser.add_argument("--calibration-end", default="2026-08-30")
    parser.add_argument("--history-start", default="2026-08-01")
    parser.add_argument("--history-end", default="2026-08-31")
    parser.add_argument("--reference-start", default="2026-09-23")
    parser.add_argument("--reference-end", default="2026-09-30")
    parser.add_argument("--opal-reports", type=Path, default=DEFAULT_OPAL_REPORTS)
    parser.add_argument("--september-reference", type=Path, default=DEFAULT_SEPTEMBER_REFERENCE)
    parser.add_argument("--screenshot-root", type=Path, default=DEFAULT_SCREENSHOT_ROOT)
    parser.add_argument("--apple-daily-dir", type=Path, default=DEFAULT_APPLE_DAILY_DIR)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true",
                        help="Regenerate (clears this reconstruction directory's own files first).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        missing_start = date.fromisoformat(args.missing_start)
        missing_end = date.fromisoformat(args.missing_end)
        output_dir = args.output_dir or (
            RECONSTRUCTION_ROOT / f"{missing_start.isoformat()}_{missing_end.isoformat()}"
        )
        summary = run(
            opal_reports_path=args.opal_reports,
            screenshot_root=args.screenshot_root,
            apple_daily_dir=args.apple_daily_dir,
            output_dir=output_dir,
            missing_start=missing_start,
            missing_end=missing_end,
            calibration_start=date.fromisoformat(args.calibration_start),
            calibration_end=date.fromisoformat(args.calibration_end),
            history_start=date.fromisoformat(args.history_start),
            history_end=date.fromisoformat(args.history_end),
            september_reference_path=args.september_reference,
            reference_start=date.fromisoformat(args.reference_start),
            reference_end=date.fromisoformat(args.reference_end),
            force=args.force,
        )
    except ReconstructionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    cal = summary["calibration"]
    sep = summary["september"]
    print("=== Opal -> Apple Screen Time Reconstruction ===")
    print(f"Method               : {summary['method_version']}")
    print(f"Opal screenshots     : {summary['opal_screenshots_discovered']} discovered, "
          f"{summary['opal_reports']} reports; untranscribed {summary['opal_screenshots_untranscribed']}")
    print(f"Report issues        : {summary['opal_report_issues'] or 'none'}")
    print(f"Calibration          : {cal['first_date']} .. {cal['last_date']} ({cal['days']} days) "
          f"— {summary['calibration_status']}")
    print(f"Apple / Opal totals  : {cal['total_apple_minutes']:.1f} / {cal['total_opal_minutes']:.0f} min")
    print(f"Opal / Apple         : {cal['overall_opal_over_apple']:.4f}")
    print(f"Mean daily A-O       : {cal['mean_daily_difference_min']:.4f} min")
    print(f"Correlation r        : {cal['correlation_r']:.4f}")
    for m in summary["models"]:
        print(f"  {m['model']:<17} in-sample MAE {m['in_sample_mae_min']:5.1f} RMSE {m['in_sample_rmse_min']:5.1f}"
              f" | LOWO-CV MAE {m['lowo_cv_mae_min']:5.1f} RMSE {m['lowo_cv_rmse_min']:5.1f}")
    print("Category validation (leave-one-day-out, mean daily misallocated):")
    for s in summary["category_summary"]:
        print(f"  {s['Model']:<27} {s['Mean_Daily_Misallocated_Min']:6.1f} min "
              f"({s['Mean_Daily_Misallocated_Pct_Of_Total']:.1f}%) | period {s['Period_Misallocated_Min']:.1f} min")
    print(f"Category model       : {summary['category_model']} — {summary['category_selection_reason']}")
    if sep.get("days"):
        print(f"Aug vs Sep (visible) : {sep['days']} Sep days, TVD {sep['tvd'] * 100:.1f} pp, "
              f"max major {sep['max_major_pp']:.1f} pp -> "
              f"{'broadly consistent' if sep['consistent'] else 'NOT consistent'}")
    print(f"Missing period       : {summary['missing_period'][0]} .. {summary['missing_period'][1]}")
    print(f"Estimated dates      : {len(summary['estimated_dates'])}")
    print(f"No Opal evidence     : {summary['no_opal_dates']}")
    print(f"Skipped (observed)   : {summary['skipped_observed_dates']}")
    print(f"REVIEW dates         : {summary['review_dates']}")
    print(f"Estimated total      : {summary['estimated_total_minutes']} min "
          f"(Opal {summary['estimated_total_opal_minutes']} min)")
    print(f"Output               : {summary['output_dir']}")
    status = "REVIEW" if (summary["review_dates"] or summary["opal_screenshots_untranscribed"]
                          or summary["opal_report_issues"]) else "PASS"
    print(f"RESULT: RECONSTRUCTION LAYER BUILT — STATUS {status}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
