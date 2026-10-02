from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_ROOT = PROJECT_ROOT / "input" / "Habit"
OUTPUT_ROOT = PROJECT_ROOT / "output"
RAW_ROOT = OUTPUT_ROOT / "Raw" / "Habit"
API_ROOT = OUTPUT_ROOT / "Analysis" / "API"
USAGE_LEDGER = API_ROOT / "OpenAI_Usage_v2.csv"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

STANDARD_CATEGORIES = (
    "Workout", "Read a book", "Meditation", "Offline Study Tracker",
    "Offline Work Tracking", "Family Time Tracking", "Social Time Tracking",
    "TV Time tracking", "Personal Time Tracking", "Console Time Tracking",
    "Journaling", "Sleep", "Motorcycle Time",
)

TRACKING_MODES = {
    "Workout": "daily", "Read a book": "daily", "Meditation": "daily",
    "Offline Study Tracker": "daily", "Offline Work Tracking": "daily",
    "Family Time Tracking": "weekly_cumulative",
    "Social Time Tracking": "weekly_cumulative",
    "TV Time tracking": "weekly_cumulative",
    "Personal Time Tracking": "weekly_cumulative",
    "Console Time Tracking": "weekly_cumulative",
    "Journaling": "daily", "Sleep": "daily",
    "Motorcycle Time": "monthly_cumulative",
}

ALIASES = {
    "TV Time Tracking": "TV Time tracking", "TV Time": "TV Time tracking",
    "Read Book": "Read a book", "Reading": "Read a book",
    "Offline Study": "Offline Study Tracker", "Study": "Offline Study Tracker",
    "Offline Work": "Offline Work Tracking", "Work": "Offline Work Tracking",
    "Family Time": "Family Time Tracking", "Social Time": "Social Time Tracking",
    "Personal Time": "Personal Time Tracking", "Console Time": "Console Time Tracking",
    "Journal": "Journaling", "Motorcycle": "Motorcycle Time",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class Screenshot:
    path: Path
    sha256: str
    size_bytes: int


@dataclass
class Usage:
    attempts: int = 0
    responses: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class IngestionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract Habit tracker state from screenshots.")
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--date", dest="dates", action="append", help="YYYY-MM-DD; repeatable")
    p.add_argument("--dry", "--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def validate_month(value: str) -> str:
    try:
        return date.fromisoformat(value + "-01").strftime("%Y-%m")
    except ValueError as exc:
        raise IngestionError(f"Invalid month '{value}'. Expected YYYY-MM.") from exc


def validate_date(value: str, month: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise IngestionError(f"Invalid date '{value}'.") from exc
    if parsed.strftime("%Y-%m") != month:
        raise IngestionError(f"{value} is outside {month}.")
    return parsed.isoformat()


def discover_dates(month: str, requested: list[str] | None) -> list[str]:
    root = INPUT_ROOT / month
    if requested:
        return sorted({validate_date(v, month) for v in requested})
    if not root.exists():
        raise IngestionError(f"Habit input directory does not exist: {root}")
    return sorted(
        child.name for child in root.iterdir()
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name)
    )


def screenshot_paths(month: str, target_date: str) -> list[Path]:
    root = INPUT_ROOT / month / target_date
    if not root.exists():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_screenshots(paths: list[Path]) -> list[Screenshot]:
    if not paths:
        raise IngestionError("No screenshots found.")
    result = []
    for path in paths:
        size = path.stat().st_size
        if size <= 0:
            raise IngestionError(f"Screenshot is empty: {path}")
        result.append(Screenshot(path, sha256_file(path), size))
    return result


def date_root(month: str, target_date: str) -> Path:
    return RAW_ROOT / month / target_date


def extraction_path(month: str, target_date: str) -> Path:
    return date_root(month, target_date) / "AI_Extraction.json"


def metadata_path(month: str, target_date: str) -> Path:
    return date_root(month, target_date) / "AI_Metadata.json"


def candidate_path(month: str, target_date: str) -> Path:
    return date_root(month, target_date) / "AI_Extraction_Candidate.json"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def screenshot_metadata(items: list[Screenshot]) -> list[dict[str, Any]]:
    return [
        {"filename": x.path.name, "size_bytes": x.size_bytes, "sha256": x.sha256}
        for x in items
    ]


def screenshots_match(items: list[Screenshot], metadata: dict[str, Any] | None) -> bool:
    return bool(metadata and metadata.get("screenshots") == screenshot_metadata(items))


def period_start(target_date: str, mode: str) -> str:
    d = date.fromisoformat(target_date)
    if mode == "weekly_cumulative":
        return (d.fromordinal(d.toordinal() - d.weekday())).isoformat()
    if mode == "monthly_cumulative":
        return d.replace(day=1).isoformat()
    return d.isoformat()


def duration(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise IngestionError("Duration cannot be boolean.")
    if isinstance(value, (int, float)):
        if int(value) < 0:
            raise IngestionError("Duration cannot be negative.")
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return 0
    if text.isdigit():
        return int(text) * 60
    matches = re.findall(r"(\d+)\s*([hms])", text)
    if not matches or "".join(n + u for n, u in matches).replace(" ", "") != text.replace(" ", ""):
        raise IngestionError(f"Unsupported duration: {value!r}")
    return sum(
        int(n) * {"h": 3600, "m": 60, "s": 1}[u]
        for n, u in matches
    )


def fmt(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return " ".join(x for x in (f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s" if s else "") if x) or "0m"


def canonical(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if normalized in STANDARD_CATEGORIES:
        return normalized
    if normalized in ALIASES:
        return ALIASES[normalized]
    for category in STANDARD_CATEGORIES:
        if normalized.casefold() == category.casefold():
            return category
    raise IngestionError(f"Unknown Habit category: {value!r}")


def build_prompt(target_date: str) -> str:
    taxonomy = "\n".join(
        f"- {c}: {TRACKING_MODES[c]}" for c in STANDARD_CATEGORIES
    )
    return f"""
Extract tracker STATE from the supplied Habit / OffDevice screenshots for {target_date}.

Tracking semantics:
- daily: displayed completed value is that calendar day's value.
- weekly_cumulative: displayed completed value accumulates from Monday through the current date.
- monthly_cumulative: displayed completed value accumulates from the first day of the current month.
- Weekly trackers restart every Monday.
- Motorcycle Time is monthly_cumulative and restarts on the first day of each month.

Taxonomy:
{taxonomy}

Critical rules:
1. Extract the CURRENT COMPLETED VALUE, not the budget.
2. In "335/120m", current_value_sec=20100 and budget_sec=7200.
3. The 120m is a target/budget and MUST NOT become observed time.
4. For cumulative trackers, return the cumulative current value only.
5. Python will calculate daily deltas from consecutive states; do not calculate them.
6. Do not infer missing time, cap values, or estimate progress-bar widths.
7. Combine the supplied screenshots for this date.
8. Return zero if a category is not visible.
9. Return exactly one entry for every taxonomy category.

Return ONLY JSON:
{{
  "date": "{target_date}",
  "categories": [
    {{
      "category": "Family Time Tracking",
      "display_label": "Family Time Tracking",
      "tracking_mode": "weekly_cumulative",
      "current_value_sec": 0,
      "budget_sec": null,
      "period_start": "{period_start(target_date, "weekly_cumulative")}",
      "visible": false,
      "evidence": "Not visible"
    }}
  ],
  "warnings": []
}}
""".strip()


def api_input(target_date: str, screenshots: list[Screenshot]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": build_prompt(target_date)}]
    for shot in screenshots:
        encoded = base64.b64encode(shot.path.read_bytes()).decode("ascii")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[shot.path.suffix.lower()]
        content.append({
            "type": "input_image",
            "image_url": f"data:{mime};base64,{encoded}",
            "detail": "high",
        })
    return [{"role": "user", "content": content}]


def response_json(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if not isinstance(text, str):
        raise IngestionError("OpenAI response did not contain output_text.")
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestionError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise IngestionError("Model JSON root must be an object.")
    return value


def extract(client: OpenAI, model: str, target_date: str, screenshots: list[Screenshot], usage: Usage) -> dict[str, Any]:
    for attempt in range(1, 7):
        usage.attempts += 1
        try:
            response = client.responses.create(
                model=model,
                input=api_input(target_date, screenshots),
            )
            usage.responses += 1
            u = getattr(response, "usage", None)
            if u:
                usage.input_tokens += int(getattr(u, "input_tokens", 0) or 0)
                usage.output_tokens += int(getattr(u, "output_tokens", 0) or 0)
                details = getattr(u, "input_tokens_details", None)
                usage.cached_input_tokens += int(getattr(details, "cached_tokens", 0) or 0)
            return response_json(response)
        except Exception as exc:
            text = str(exc).lower()
            if not any(x in text for x in ("429", "rate limit", "rate_limit_exceeded")) or attempt == 6:
                raise IngestionError(f"OpenAI extraction failed: {exc}") from exc
            wait = min(2 ** (attempt - 1), 16)
            print(f"RATE LIMIT | attempt={attempt}/6 | waiting={wait}s")
            time.sleep(wait)
    raise IngestionError("OpenAI extraction failed after retries.")


def normalize(raw: dict[str, Any], target_date: str, screenshots: list[Screenshot]) -> dict[str, Any]:
    categories = raw.get("categories")
    if not isinstance(categories, list):
        raise IngestionError("Model extraction is missing categories.")

    by_name: dict[str, dict[str, Any]] = {}
    for item in categories:
        if not isinstance(item, dict) or not isinstance(item.get("category"), str):
            raise IngestionError("Invalid category entry.")
        category = canonical(item["category"])
        if category in by_name:
            raise IngestionError(f"Duplicate category: {category}")

        expected_mode = TRACKING_MODES[category]
        mode = str(item.get("tracking_mode", expected_mode)).strip().casefold()
        mode = {"weekly": "weekly_cumulative", "monthly": "monthly_cumulative"}.get(mode, mode)
        if mode != expected_mode:
            raise IngestionError(
                f"Tracking mode mismatch for {category}: expected {expected_mode}, got {mode!r}"
            )

        current = duration(item.get("current_value_sec", 0))
        budget = None if item.get("budget_sec") is None else duration(item["budget_sec"])
        start = item.get("period_start") or period_start(target_date, expected_mode)
        if start != period_start(target_date, expected_mode):
            raise IngestionError(f"Invalid period_start for {category}: {start!r}")

        by_name[category] = {
            "category": category,
            "display_label": str(item.get("display_label") or category),
            "tracking_mode": expected_mode,
            "current_value_sec": current,
            "current_value_display": fmt(current),
            "budget_sec": budget,
            "budget_display": None if budget is None else fmt(budget),
            "period_start": start,
            "visible": bool(item.get("visible", current > 0)),
            "evidence": str(item.get("evidence") or "Visible in screenshot"),
        }

    normalized = []
    for category in STANDARD_CATEGORIES:
        if category in by_name:
            normalized.append(by_name[category])
        else:
            mode = TRACKING_MODES[category]
            normalized.append({
                "category": category,
                "display_label": category,
                "tracking_mode": mode,
                "current_value_sec": 0,
                "current_value_display": "0m",
                "budget_sec": None,
                "budget_display": None,
                "period_start": period_start(target_date, mode),
                "visible": False,
                "evidence": "Not visible in screenshot",
            })

    return {
        "date": target_date,
        "source": "Habit / OffDevice Tracker",
        "taxonomy_version": 2,
        "tracking_semantics_version": 1,
        "categories": normalized,
        "screenshots_reviewed": [x.path.name for x in screenshots],
        "warnings": [str(x) for x in raw.get("warnings", [])] if isinstance(raw.get("warnings", []), list) else [],
    }


def validate(extraction: dict[str, Any], target_date: str) -> None:
    if extraction.get("date") != target_date:
        raise IngestionError("Extraction date mismatch.")
    categories = extraction.get("categories")
    if not isinstance(categories, list) or [x.get("category") for x in categories] != list(STANDARD_CATEGORIES):
        raise IngestionError("Canonical taxonomy does not match exactly.")
    for item in categories:
        category = item["category"]
        if item["tracking_mode"] != TRACKING_MODES[category]:
            raise IngestionError(f"Invalid tracking mode for {category}.")
        if not isinstance(item["current_value_sec"], int) or item["current_value_sec"] < 0:
            raise IngestionError(f"Invalid current value for {category}.")
        if item["period_start"] != period_start(target_date, TRACKING_MODES[category]):
            raise IngestionError(f"Invalid period start for {category}.")


def estimate_cost(model: str, usage: Usage) -> float:
    if model != "gpt-4o-mini":
        return 0.0
    billable = max(usage.input_tokens - usage.cached_input_tokens, 0)
    return billable * 0.15 / 1_000_000 + usage.cached_input_tokens * 0.075 / 1_000_000 + usage.output_tokens * 0.60 / 1_000_000


def append_usage(target_date: str, model: str, usage: Usage) -> None:
    USAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    exists = USAGE_LEDGER.exists()
    fields = ["timestamp", "date", "pipeline", "model", "attempts", "responses", "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd"]
    with USAGE_LEDGER.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "date": target_date,
            "pipeline": "habit_offdevice_ingest",
            "model": model,
            "attempts": usage.attempts,
            "responses": usage.responses,
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "estimated_cost_usd": f"{usage.estimated_cost_usd:.6f}",
        })


def process(month: str, target_date: str, model: str, client: OpenAI | None, dry: bool, force: bool) -> tuple[str, Usage]:
    root = date_root(month, target_date)
    root.mkdir(parents=True, exist_ok=True)
    screenshots = inspect_screenshots(screenshot_paths(month, target_date))
    usage = Usage()
    metadata = load_json(metadata_path(month, target_date))

    if not dry and not force and screenshots_match(screenshots, metadata) and extraction_path(month, target_date).exists():
        print(f"{target_date} | UNCHANGED | cached extraction reused | 0 API calls")
        return "UNCHANGED", usage

    if dry:
        print(f"{target_date} | READY | {len(screenshots)} screenshots")
        return "READY", usage

    if client is None:
        raise IngestionError("OpenAI client is not configured.")

    raw = extract(client, model, target_date, screenshots, usage)
    normalized = normalize(raw, target_date, screenshots)
    validate(normalized, target_date)

    usage.estimated_cost_usd = estimate_cost(model, usage)

    write_json(candidate_path(month, target_date), {
        "date": target_date,
        "raw_extraction": raw,
        "screenshots": screenshot_metadata(screenshots),
    })
    write_json(extraction_path(month, target_date), normalized)
    write_json(metadata_path(month, target_date), {
        "date": target_date,
        "status": "canonical",
        "model": model,
        "taxonomy_version": 2,
        "tracking_semantics": {
            "weekly_restart": "Monday",
            "monthly_restart": "first day of month",
            "budget_is_not_observed_time": True,
            "daily_delta_calculated_by": "habit_offdevice_builder.py",
        },
        "screenshots": screenshot_metadata(screenshots),
        "usage": usage.__dict__,
        "ingestion_method": "habit_offdevice_tracker_state",
    })
    append_usage(target_date, model, usage)

    nonzero = sum(x["current_value_sec"] > 0 for x in normalized["categories"])
    print(f"{target_date} | NEW | {nonzero} nonzero current values | ${usage.estimated_cost_usd:.6f}")
    return "NEW", usage


def main() -> int:
    args = parse_args()
    try:
        month = validate_month(args.month)
        dates = discover_dates(month, args.dates)
        if not dates:
            raise IngestionError(f"No Habit dates found for {month}.")

        print("# Habit / OffDevice Tracker State Ingestion")
        print(f"Month : {month}")
        print(f"Dates : {', '.join(dates)}")
        print(f"Force : {args.force}")
        print("Weekly cumulative trackers restart every Monday.")
        print("Motorcycle Time restarts every first day of month.")
        print("Budget values are extracted separately and never treated as observed time.")
        print()

        client = None
        if not args.dry_run:
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise IngestionError("OPENAI_API_KEY is not configured.")
            client = OpenAI(api_key=key)

        results = []
        total = Usage()
        for target_date in dates:
            try:
                result, usage = process(month, target_date, args.model, client, args.dry_run, args.force)
                results.append(result)
                for field in ("attempts", "responses", "input_tokens", "cached_input_tokens", "output_tokens"):
                    setattr(total, field, getattr(total, field) + getattr(usage, field))
                total.estimated_cost_usd += usage.estimated_cost_usd
            except Exception as exc:
                results.append("FAILED")
                print(f"{target_date} | FAILED | {type(exc).__name__}: {exc}")

        print()
        print("=== HABIT / OFFDEVICE INGESTION SUMMARY ===")
        for status in ("READY", "NEW", "UNCHANGED", "FAILED"):
            print(f"{status:<12}: {results.count(status)}")
        print(f"API calls attempted : {total.attempts}")
        print(f"Input tokens        : {total.input_tokens:,}")
        print(f"Output tokens       : {total.output_tokens:,}")
        print(f"Estimated cost      : ${total.estimated_cost_usd:.6f}")

        if "FAILED" in results:
            print("RESULT: HABIT / OFFDEVICE INGESTION FAILED.")
            return 1
        print("RESULT: HABIT / OFFDEVICE STATE INGESTION PASSED.")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        print("RESULT: HABIT / OFFDEVICE INGESTION FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())