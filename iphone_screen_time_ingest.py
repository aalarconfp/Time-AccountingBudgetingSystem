# FILE: iphone_screen_time_ingest.py

"""AI-assisted Apple Screen Time screenshot ingestion.

Each completed date should contain exactly three screenshots:

1. Total Screen Time.
2. Category breakdown.
3. Social application detail.

The AI extracts visible evidence only.

Duration arithmetic is performed deterministically by Python.

The Apple headline Screen Time value is retained as a reconciliation
reference. Visible category time is the primary observed activity data.

When the headline exceeds the visible category total, the difference is
preserved as a derived "Apple Screen Time Unresolved" bucket. It is not
classified as Off-Device.

When visible categories exceed the headline, the date receives a
reconciliation warning and the discrepancy is not silently forced.

Original screenshots remain untouched.

Temporary OpenAI TPM rate limits are retried automatically. Billing,
authentication, model, validation, and other non-rate-limit errors are
not retried.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError


PROJECT_ROOT = Path(__file__).resolve().parent

SCREEN_TIME_INPUT = (
    PROJECT_ROOT
    / "input"
    / "iPhone"
    / "ScreenTime"
)

RAW_OUTPUT = (
    PROJECT_ROOT
    / "output"
    / "Raw"
    / "AppleScreenTime"
    / "iPhone"
)

API_OUTPUT = (
    PROJECT_ROOT
    / "output"
    / "Analysis"
    / "API"
)

CURRENT_USAGE_LEDGER = (
    API_OUTPUT
    / "OpenAI_Usage_v2.csv"
)

LEGACY_USAGE_LEDGER = (
    API_OUTPUT
    / "OpenAI_Usage.csv"
)

LEGACY_BACKUP_LEDGER = (
    API_OUTPUT
    / "OpenAI_Usage_legacy.csv"
)

SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

DEFAULT_MODEL = os.getenv(
    "OPENAI_MODEL",
    "",
)

MODEL_PRICING_USD_PER_MILLION: dict[
    str,
    dict[str, float],
] = {
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}

OPTIMIZED_MAX_DIMENSION = 1600
OPTIMIZED_JPEG_QUALITY = 88

MAX_RATE_LIMIT_RETRIES = 6
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0
MAX_RATE_LIMIT_WAIT_SECONDS = 90.0

UNRESOLVED_CATEGORY_NAME = (
    "Apple Screen Time Unresolved"
)

USAGE_FIELDS = (
    "timestamp_utc",
    "ledger_version",
    "date",
    "status",
    "operation",
    "model",
    "api_calls_attempted",
    "api_responses_received",
    "screenshot_count",
    "original_screenshot_bytes",
    "optimized_image_bytes",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_tokens",
    "estimated_input_cost_usd",
    "estimated_cached_input_cost_usd",
    "estimated_output_cost_usd",
    "estimated_total_cost_usd",
    "content_hash",
    "error_type",
    "error_message",
)


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "date": {
            "type": "string",
        },
        "screenshot_roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "filename": {
                        "type": "string",
                    },
                    "role": {
                        "type": "string",
                        "enum": [
                            "TOTAL",
                            "CATEGORIES",
                            "SOCIAL",
                        ],
                    },
                    "confidence": {
                        "type": "number",
                    },
                },
                "required": [
                    "filename",
                    "role",
                    "confidence",
                ],
            },
        },
        "total_screen_time_display": {
            "type": "string",
        },
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "apple_category": {
                        "type": "string",
                    },
                    "duration_display": {
                        "type": "string",
                    },
                },
                "required": [
                    "apple_category",
                    "duration_display",
                ],
            },
        },
        "social_apps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "app": {
                        "type": "string",
                    },
                    "duration_display": {
                        "type": "string",
                    },
                },
                "required": [
                    "app",
                    "duration_display",
                ],
            },
        },
        "social_detail_complete": {
            "type": "boolean",
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "date",
        "screenshot_roles",
        "total_screen_time_display",
        "categories",
        "social_apps",
        "social_detail_complete",
        "warnings",
    ],
}


EXTRACTION_INSTRUCTIONS = """
You are the evidence-extraction component of a personal time-tracking
system.

You are given exactly three Apple Screen Time screenshots belonging to
ONE calendar day.

Identify exactly one screenshot for each role:

1. TOTAL
   The Apple Screen Time screen showing overall daily Screen Time.

2. CATEGORIES
   The screen showing the Apple Screen Time category breakdown.

3. SOCIAL
   The screen showing the Social category application breakdown.

For every screenshot return:
- original filename;
- detected role;
- confidence from 0.0 to 1.0.

CRITICAL DURATION RULE:

Return the duration EXACTLY as displayed in the screenshot.

Examples:

"2h 8m"
"8m"
"42s"
"1h 23m"
"39s"

DO NOT convert durations to seconds.

DO NOT perform arithmetic on durations.

DO NOT interpret a value ending in "s" as minutes.

The Python program will perform all duration conversion.

TOTAL:
- Extract the displayed daily Screen Time string exactly.

CATEGORIES:
- Extract every visible Apple Screen Time category.
- Preserve Apple's category names exactly as visible.
- Preserve the displayed duration exactly.
- Do not infer missing categories.

SOCIAL:
- Extract every visible application and its displayed duration.
- Preserve the application name exactly as visible.
- Preserve the displayed duration exactly.
- Determine whether the visible application list appears complete.
- If the list is truncated or completeness cannot be established,
  set social_detail_complete to false.

IMPORTANT:

Social application durations are detail belonging to the Social
category. They must NOT be added to the category totals.

Do not map applications or Apple categories into the project's
master taxonomy.

Do not invent values.

If a value is unclear, preserve the most defensible visible text and
add a warning.

If screenshots appear to conflict, preserve the visible evidence and
add a warning.

The folder date is authoritative for the expected calendar date.

Return ONLY structured JSON matching the supplied schema.
"""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract Apple Screen Time screenshots "
            "with AI."
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
            "Process one date. May be specified multiple "
            "times for an explicit date list."
        ),
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "OpenAI model. Can also be supplied "
            "through OPENAI_MODEL."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Replace canonical extraction after "
            "successful processing."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate screenshot coverage without "
            "calling OpenAI."
        ),
    )

    return parser.parse_args()


def parse_month(value: str) -> tuple[int, int]:
    """Validate a YYYY-MM month."""
    try:
        year_text, month_text = value.split("-")
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
    """Validate an ISO date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def validate_model(model: str) -> str:
    """Validate the configured model."""
    model = model.strip()

    if not model:
        raise RuntimeError(
            "No OpenAI model configured. "
            "Set OPENAI_MODEL or pass --model."
        )

    if model not in MODEL_PRICING_USD_PER_MILLION:
        raise RuntimeError(
            f"No API pricing configuration exists "
            f"for '{model}'. Add current pricing before "
            "using this model."
        )

    return model


def create_client() -> OpenAI:
    """Create an OpenAI API client."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not configured."
        )

    return OpenAI()


def list_date_directories(
    month: str,
    target_dates: list[str] | None,
) -> list[Path]:
    """Return date directories to inspect."""
    parse_month(month)

    month_directory = (
        SCREEN_TIME_INPUT / month
    )

    if not month_directory.exists():
        raise FileNotFoundError(
            "Missing Screen Time month directory: "
            f"{month_directory}"
        )

    if target_dates:
        directories: list[Path] = []

        for target_date in target_dates:
            parsed = parse_date(target_date)

            if parsed.strftime("%Y-%m") != month:
                raise ValueError(
                    f"{target_date} is outside {month}."
                )

            directory = (
                month_directory / target_date
            )

            if not directory.exists():
                raise FileNotFoundError(
                    "Missing Screen Time date directory: "
                    f"{directory}"
            )

            directories.append(directory)

        return directories

    return sorted(
        directory
        for directory in month_directory.iterdir()
        if directory.is_dir()
        and directory.name.startswith(month)
    )


def discover_screenshots(
    date_directory: Path,
) -> tuple[Path, ...]:
    """Return supported screenshot files."""
    return tuple(
        sorted(
            path
            for path in date_directory.iterdir()
            if path.is_file()
            and path.suffix.lower()
            in SUPPORTED_IMAGE_TYPES
        )
    )


def classify_screenshot_coverage(
    screenshots: tuple[Path, ...],
) -> str:
    """Classify screenshot coverage."""
    if len(screenshots) == 0:
        return "PENDING"

    if len(screenshots) == 3:
        return "READY"

    return "INVALID"


def calculate_content_hash(
    screenshot_paths: tuple[Path, ...],
) -> str:
    """Hash screenshot names and contents."""
    digest = hashlib.sha256()

    for path in screenshot_paths:
        digest.update(
            path.name.encode("utf-8")
        )
        digest.update(
            path.read_bytes()
        )

    return digest.hexdigest()


def calculate_file_hash(
    path: Path,
) -> str:
    """Return a SHA-256 file hash."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def output_paths(
    target_date: str,
) -> dict[str, Path]:
    """Return output paths for one date."""
    date_directory = (
        RAW_OUTPUT
        / target_date[:7]
        / target_date
    )

    return {
        "directory": date_directory,
        "extraction": (
            date_directory
            / "AI_Extraction.json"
        ),
        "metadata": (
            date_directory
            / "AI_Metadata.json"
        ),
        "candidate_extraction": (
            date_directory
            / "AI_Extraction_Candidate.json"
        ),
        "candidate_metadata": (
            date_directory
            / "AI_Metadata_Candidate.json"
        ),
    }


def load_json(
    path: Path,
) -> dict[str, Any]:
    """Load a JSON object."""
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def downstream_output_exists(
    target_date: str,
) -> bool:
    """Detect existing iPhone downstream data."""
    fact_path = (
        PROJECT_ROOT
        / "output"
        / "Fact"
        / "Time"
        / "AppleScreenTime"
        / "iPhone"
        / f"Fact_Time_{target_date}.csv"
    )

    daily_path = (
        PROJECT_ROOT
        / "output"
        / "Daily"
        / "Time"
        / "AppleScreenTime"
        / "iPhone"
        / f"Daily_Time_{target_date}.csv"
    )

    return (
        fact_path.exists()
        or daily_path.exists()
    )


def duration_to_seconds(
    duration: str,
) -> int:
    """Convert an Apple duration string to seconds."""
    value = (
        duration
        .strip()
        .lower()
        .replace(" ", "")
    )

    if not value:
        raise ValueError(
            "Empty duration."
        )

    matches = re.findall(
        r"(\d+)([hms])",
        value,
    )

    if not matches:
        raise ValueError(
            f"Unsupported Apple duration: "
            f"'{duration}'"
        )

    reconstructed = "".join(
        f"{number}{unit}"
        for number, unit in matches
    )

    if reconstructed != value:
        raise ValueError(
            f"Unsupported Apple duration: "
            f"'{duration}'"
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


def seconds_to_duration(
    seconds: int,
) -> str:
    """Format seconds as a human-readable duration."""
    if seconds < 0:
        raise ValueError(
            "Duration cannot be negative."
        )

    hours, remainder = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    parts: list[str] = []

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if seconds or not parts:
        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts)


def calculate_costs(
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> dict[str, float]:
    """Calculate estimated API costs."""
    pricing = (
        MODEL_PRICING_USD_PER_MILLION[
            model
        ]
    )

    uncached_input_tokens = max(
        input_tokens - cached_input_tokens,
        0,
    )

    input_cost = (
        uncached_input_tokens
        / 1_000_000
        * pricing["input"]
    )

    cached_input_cost = (
        cached_input_tokens
        / 1_000_000
        * pricing["cached_input"]
    )

    output_cost = (
        output_tokens
        / 1_000_000
        * pricing["output"]
    )

    return {
        "input": input_cost,
        "cached_input": cached_input_cost,
        "output": output_cost,
        "total": (
            input_cost
            + cached_input_cost
            + output_cost
        ),
    }


def ensure_current_usage_ledger() -> None:
    """Create the current usage ledger."""
    API_OUTPUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    if CURRENT_USAGE_LEDGER.exists():
        return

    with CURRENT_USAGE_LEDGER.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=USAGE_FIELDS,
        )
        writer.writeheader()


def preserve_legacy_ledger() -> None:
    """Preserve the old ledger without modifying it."""
    if not LEGACY_USAGE_LEDGER.exists():
        return

    if LEGACY_BACKUP_LEDGER.exists():
        return

    shutil.copy2(
        LEGACY_USAGE_LEDGER,
        LEGACY_BACKUP_LEDGER,
    )


def append_usage_record(
    *,
    target_date: str,
    status: str,
    operation: str,
    model: str,
    api_calls_attempted: int,
    api_responses_received: int,
    screenshot_count: int,
    original_screenshot_bytes: int,
    optimized_image_bytes: int,
    content_hash: str,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    error_type: str = "",
    error_message: str = "",
) -> float:
    """Append one API usage record."""
    ensure_current_usage_ledger()

    total_tokens = (
        input_tokens
        + output_tokens
    )

    costs = calculate_costs(
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=(
            cached_input_tokens
        ),
        output_tokens=output_tokens,
    )

    row = {
        "timestamp_utc": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
        "ledger_version": "2",
        "date": target_date,
        "status": status,
        "operation": operation,
        "model": model,
        "api_calls_attempted": (
            api_calls_attempted
        ),
        "api_responses_received": (
            api_responses_received
        ),
        "screenshot_count": screenshot_count,
        "original_screenshot_bytes": (
            original_screenshot_bytes
        ),
        "optimized_image_bytes": (
            optimized_image_bytes
        ),
        "input_tokens": input_tokens,
        "cached_input_tokens": (
            cached_input_tokens
        ),
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_input_cost_usd": (
            f"{costs['input']:.10f}"
        ),
        "estimated_cached_input_cost_usd": (
            f"{costs['cached_input']:.10f}"
        ),
        "estimated_output_cost_usd": (
            f"{costs['output']:.10f}"
        ),
        "estimated_total_cost_usd": (
            f"{costs['total']:.10f}"
        ),
        "content_hash": content_hash,
        "error_type": error_type,
        "error_message": error_message,
    }

    with CURRENT_USAGE_LEDGER.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=USAGE_FIELDS,
        )
        writer.writerow(row)

    return costs["total"]


def read_current_usage_summary() -> dict[str, float]:
    """Read the current usage ledger."""
    if not CURRENT_USAGE_LEDGER.exists():
        return {
            "attempted": 0,
            "responses": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }

    attempted = 0
    responses = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cost = 0.0

    with CURRENT_USAGE_LEDGER.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            attempted += int(
                row.get(
                    "api_calls_attempted",
                    0,
                )
                or 0
            )

            responses += int(
                row.get(
                    "api_responses_received",
                    0,
                )
                or 0
            )

            input_tokens += int(
                row.get(
                    "input_tokens",
                    0,
                )
                or 0
            )

            cached_input_tokens += int(
                row.get(
                    "cached_input_tokens",
                    0,
                )
                or 0
            )

            output_tokens += int(
                row.get(
                    "output_tokens",
                    0,
                )
                or 0
            )

            total_tokens += int(
                row.get(
                    "total_tokens",
                    0,
                )
                or 0
            )

            cost += float(
                row.get(
                    "estimated_total_cost_usd",
                    0,
                )
                or 0
            )

    return {
        "attempted": attempted,
        "responses": responses,
        "input_tokens": input_tokens,
        "cached_input_tokens": (
            cached_input_tokens
        ),
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
    }


def read_legacy_usage_summary() -> dict[str, Any]:
    """Read best-effort legacy usage information."""
    if not LEGACY_USAGE_LEDGER.exists():
        return {
            "exists": False,
            "rows": 0,
            "cost": None,
        }

    rows = 0
    cost_values: list[float] = []

    try:
        with LEGACY_USAGE_LEDGER.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)

            if reader.fieldnames is None:
                return {
                    "exists": True,
                    "rows": 0,
                    "cost": None,
                }

            for row in reader:
                rows += 1

                value = row.get(
                    "estimated_total_cost_usd"
                )

                if value:
                    try:
                        cost_values.append(
                            float(value)
                        )
                    except ValueError:
                        pass

    except (OSError, csv.Error):
        return {
            "exists": True,
            "rows": rows,
            "cost": None,
        }

    return {
        "exists": True,
        "rows": rows,
        "cost": (
            sum(cost_values)
            if cost_values
            else None
        ),
    }


def optimize_image(
    path: Path,
) -> tuple[bytes, str]:
    """Resize an image for API transmission."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for screenshot "
            "optimization. Install it with: "
            "python -m pip install Pillow"
        ) from exc

    with Image.open(path) as image:
        image = image.convert("RGB")

        width, height = image.size
        largest_dimension = max(
            width,
            height,
        )

        if (
            largest_dimension
            > OPTIMIZED_MAX_DIMENSION
        ):
            scale = (
                OPTIMIZED_MAX_DIMENSION
                / largest_dimension
            )

            new_size = (
                max(
                    1,
                    round(width * scale),
                ),
                max(
                    1,
                    round(height * scale),
                ),
            )

            image = image.resize(
                new_size,
                Image.Resampling.LANCZOS,
            )

        buffer = io.BytesIO()

        image.save(
            buffer,
            format="JPEG",
            quality=OPTIMIZED_JPEG_QUALITY,
            optimize=True,
        )

        return (
            buffer.getvalue(),
            "image/jpeg",
        )


def image_bytes_to_data_url(
    image_bytes: bytes,
    media_type: str,
) -> str:
    """Convert image bytes to a data URL."""
    encoded = base64.b64encode(
        image_bytes
    ).decode("ascii")

    return (
        f"data:{media_type};base64,{encoded}"
    )


def prepare_images(
    screenshots: tuple[Path, ...],
) -> tuple[
    list[tuple[Path, bytes, str]],
    int,
]:
    """Prepare optimized images."""
    prepared: list[
        tuple[Path, bytes, str]
    ] = []

    total_bytes = 0

    for path in screenshots:
        image_bytes, media_type = (
            optimize_image(path)
        )

        prepared.append(
            (
                path,
                image_bytes,
                media_type,
            )
        )

        total_bytes += len(image_bytes)

    return (
        prepared,
        total_bytes,
    )


def get_usage_value(
    usage: Any,
    attribute: str,
    default: int = 0,
) -> int:
    """Read an integer usage value."""
    value = getattr(
        usage,
        attribute,
        default,
    )

    if value is None:
        return default

    return int(value)


def get_cached_input_tokens(
    usage: Any,
) -> int:
    """Read cached input tokens."""
    prompt_details = getattr(
        usage,
        "prompt_tokens_details",
        None,
    )

    if prompt_details is None:
        prompt_details = getattr(
            usage,
            "input_tokens_details",
            None,
        )

    if prompt_details is None:
        return 0

    cached_tokens = getattr(
        prompt_details,
        "cached_tokens",
        0,
    )

    if cached_tokens is None:
        return 0

    return int(cached_tokens)


def get_rate_limit_retry_seconds(
    exc: RateLimitError,
    retry_number: int,
) -> float:
    """Determine a bounded wait for a temporary rate limit."""
    response = getattr(
        exc,
        "response",
        None,
    )

    if response is not None:
        headers = getattr(
            response,
            "headers",
            None,
        )

        if headers:
            retry_after = headers.get(
                "retry-after"
            )

            if retry_after:
                try:
                    return min(
                        max(
                            float(retry_after),
                            0.0,
                        ),
                        MAX_RATE_LIMIT_WAIT_SECONDS,
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

    message = str(exc)

    marker = "Please try again in "

    if marker in message:
        remainder = message.split(
            marker,
            1,
        )[1]

        match = re.search(
            r"([\d.]+)\s*ms",
            remainder,
            flags=re.IGNORECASE,
        )

        if match:
            milliseconds = float(
                match.group(1)
            )

            return min(
                max(
                    milliseconds / 1000.0,
                    0.0,
                ),
                MAX_RATE_LIMIT_WAIT_SECONDS,
            )

        match = re.search(
            r"([\d.]+)\s*s",
            remainder,
            flags=re.IGNORECASE,
        )

        if match:
            seconds = float(
                match.group(1)
            )

            return min(
                max(seconds, 0.0),
                MAX_RATE_LIMIT_WAIT_SECONDS,
            )

    exponential_wait = (
        DEFAULT_RATE_LIMIT_WAIT_SECONDS
        * (
            2
            ** max(
                retry_number - 1,
                0,
            )
        )
    )

    return min(
        exponential_wait,
        MAX_RATE_LIMIT_WAIT_SECONDS,
    )


def extract_with_ai(
    client: OpenAI,
    prepared_images: list[
        tuple[Path, bytes, str]
    ],
    target_date: str,
    model: str,
) -> tuple[
    dict[str, Any],
    Any,
    int,
]:
    """Send screenshots to the vision model with rate-limit retries."""
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                EXTRACTION_INSTRUCTIONS
                + "\n\nEXPECTED DATE: "
                + target_date
            ),
        }
    ]

    for (
        path,
        image_bytes,
        media_type,
    ) in prepared_images:
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"Original filename: "
                    f"{path.name}"
                ),
            }
        )

        content.append(
            {
                "type": "input_image",
                "image_url": (
                    image_bytes_to_data_url(
                        image_bytes,
                        media_type,
                    )
                ),
                "detail": "high",
            }
        )

    for attempt in range(
        1,
        MAX_RATE_LIMIT_RETRIES + 1,
    ):
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                store=False,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": (
                            "apple_screen_time_extraction"
                        ),
                        "strict": True,
                        "schema": EXTRACTION_SCHEMA,
                    }
                },
            )

            output_text = response.output_text

            if not output_text:
                raise RuntimeError(
                    "OpenAI returned an empty extraction."
                )

            try:
                extraction = json.loads(
                    output_text
                )
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "OpenAI returned invalid JSON."
                ) from exc

            return (
                extraction,
                response,
                attempt,
            )

        except RateLimitError as exc:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                raise

            wait_seconds = (
                get_rate_limit_retry_seconds(
                    exc,
                    attempt,
                )
            )

            print(
                f"{target_date} | RATE LIMIT | "
                f"attempt={attempt}/"
                f"{MAX_RATE_LIMIT_RETRIES} | "
                f"waiting={wait_seconds:.1f}s"
            )

            time.sleep(
                wait_seconds
            )

    raise RuntimeError(
        "OpenAI extraction retry loop exited unexpectedly."
    )


def validate_screenshot_roles(
    extraction: dict[str, Any],
    screenshot_paths: tuple[Path, ...],
    target_date: str,
) -> None:
    """Validate screenshot role identification."""
    if extraction.get("date") != target_date:
        raise ValueError(
            "AI date mismatch: "
            f"expected {target_date}, "
            f"received {extraction.get('date')}."
        )

    expected_filenames = {
        path.name
        for path in screenshot_paths
    }

    role_entries = extraction.get(
        "screenshot_roles",
        [],
    )

    if len(role_entries) != 3:
        raise ValueError(
            "AI did not return exactly three "
            "screenshot roles."
        )

    actual_filenames = {
        str(entry["filename"])
        for entry in role_entries
    }

    if (
        actual_filenames
        != expected_filenames
    ):
        raise ValueError(
            "AI screenshot filenames do not "
            "match the supplied files."
        )

    roles = [
        str(entry["role"])
        for entry in role_entries
    ]

    expected_roles = {
        "TOTAL",
        "CATEGORIES",
        "SOCIAL",
    }

    if set(roles) != expected_roles:
        raise ValueError(
            "Screenshot role validation failed. "
            f"Detected roles: {roles}"
        )

    if len(roles) != len(set(roles)):
        raise ValueError(
            "Screenshot role validation failed: "
            "duplicate role detected."
        )

    for entry in role_entries:
        confidence = float(
            entry["confidence"]
        )

        if not 0 <= confidence <= 1:
            raise ValueError(
                "Screenshot confidence must be "
                "between 0 and 1."
            )


def normalize_extraction(
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Convert AI display durations into deterministic seconds."""
    normalized = json.loads(
        json.dumps(extraction)
    )

    total_display = str(
        normalized[
            "total_screen_time_display"
        ]
    )

    total_seconds = (
        duration_to_seconds(
            total_display
        )
    )

    normalized[
        "total_screen_time_sec"
    ] = total_seconds

    for category in normalized[
        "categories"
    ]:
        display = str(
            category[
                "duration_display"
            ]
        )

        category[
            "duration_sec"
        ] = duration_to_seconds(
            display
        )

    for app in normalized[
        "social_apps"
    ]:
        display = str(
            app[
                "duration_display"
            ]
        )

        app[
            "duration_sec"
        ] = duration_to_seconds(
            display
        )

    return normalized


def validate_and_reconcile(
    extraction: dict[str, Any],
) -> dict[str, Any]:
    """Validate normalized evidence and derive reconciliation data."""
    warnings = [
        str(warning)
        for warning in extraction.get(
            "warnings",
            [],
        )
    ]

    total_seconds = int(
        extraction[
            "total_screen_time_sec"
        ]
    )

    if total_seconds < 0:
        raise ValueError(
            "Total Screen Time cannot be negative."
        )

    categories = extraction[
        "categories"
    ]

    if not categories:
        raise ValueError(
            "No Apple Screen Time categories "
            "were extracted."
        )

    category_total = 0

    for category in categories:
        duration = int(
            category[
                "duration_sec"
            ]
        )

        if duration < 0:
            raise ValueError(
                "Category duration cannot be negative."
            )

        category_total += duration

    if category_total <= 0:
        raise ValueError(
            "Visible category time is zero."
        )

    difference = (
        total_seconds
        - category_total
    )

    reconciliation_status = (
        "MATCH"
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
            "is preserved as derived Apple "
            "Screen Time Unresolved time."
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
            "Apple reconciliation anomaly and is "
            "not converted into additional time."
        )

    social_category_seconds = next(
        (
            int(
                category[
                    "duration_sec"
                ]
            )
            for category in categories
            if (
                category[
                    "apple_category"
                ]
                .strip()
                .lower()
                == "social"
            )
        ),
        None,
    )

    social_app_seconds = sum(
        int(
            app[
                "duration_sec"
            ]
        )
        for app in extraction[
            "social_apps"
        ]
    )

    social_difference: int | None = None

    if social_category_seconds is not None:
        social_difference = (
            social_category_seconds
            - social_app_seconds
        )

        if (
            extraction[
                "social_detail_complete"
            ]
            and social_difference != 0
        ):
            warnings.append(
                "Visible Social app detail does "
                "not exactly reconcile to the Social "
                "category total. Social category time "
                "remains authoritative; app detail is "
                "supplemental evidence."
            )

    extraction[
        "category_total_sec"
    ] = category_total

    extraction[
        "category_total_display"
    ] = seconds_to_duration(
        category_total
    )

    extraction[
        "reconciliation_difference_sec"
    ] = difference

    extraction[
        "reconciliation_difference_display"
    ] = seconds_to_duration(
        abs(difference)
    )

    extraction[
        "reconciliation_status"
    ] = reconciliation_status

    extraction[
        "unresolved_screen_time_sec"
    ] = unresolved_seconds

    extraction[
        "unresolved_screen_time_display"
    ] = seconds_to_duration(
        unresolved_seconds
    )

    extraction[
        "unresolved_screen_time_allocation_type"
    ] = (
        "Derived"
        if unresolved_seconds
        else None
    )

    extraction[
        "unresolved_screen_time_category"
    ] = (
        UNRESOLVED_CATEGORY_NAME
        if unresolved_seconds
        else None
    )

    extraction[
        "unresolved_screen_time_evidence"
    ] = (
        "Reconciliation difference between "
        "Apple headline Screen Time and visible "
        "category totals."
        if unresolved_seconds
        else None
    )

    extraction[
        "social_app_total_sec"
    ] = social_app_seconds

    extraction[
        "social_app_total_display"
    ] = seconds_to_duration(
        social_app_seconds
    )

    extraction[
        "social_category_difference_sec"
    ] = social_difference

    extraction[
        "social_category_difference_display"
    ] = (
        seconds_to_duration(
            abs(social_difference)
        )
        if social_difference is not None
        else None
    )

    extraction["warnings"] = list(
        dict.fromkeys(warnings)
    )

    return extraction


def save_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Save formatted JSON."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_metadata(
    *,
    target_date: str,
    status: str,
    content_hash: str,
    model: str,
    screenshots: tuple[Path, ...],
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    estimated_cost_usd: float,
    api_calls_attempted: int,
) -> dict[str, Any]:
    """Build canonical metadata."""
    return {
        "date": target_date,
        "status": status,
        "content_hash": content_hash,
        "model": model,
        "usage": {
            "api_calls_attempted": (
                api_calls_attempted
            ),
            "api_responses_received": 1,
            "input_tokens": input_tokens,
            "cached_input_tokens": (
                cached_input_tokens
            ),
            "output_tokens": output_tokens,
            "estimated_cost_usd": (
                estimated_cost_usd
            ),
        },
        "screenshots": [
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": (
                    calculate_file_hash(
                        path
                    )
                ),
            }
            for path in screenshots
        ],
    }


def save_canonical(
    target_date: str,
    extraction: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """Save canonical extraction."""
    paths = output_paths(target_date)

    save_json(
        paths["extraction"],
        extraction,
    )

    save_json(
        paths["metadata"],
        metadata,
    )


def save_candidate(
    target_date: str,
    extraction: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """Save candidate extraction."""
    paths = output_paths(target_date)

    save_json(
        paths["candidate_extraction"],
        extraction,
    )

    save_json(
        paths["candidate_metadata"],
        metadata,
    )


def process_date(
    date_directory: Path,
    client: OpenAI | None,
    model: str,
    force: bool,
    dry_run: bool,
) -> str:
    """Process one Screen Time date."""
    target_date = date_directory.name

    screenshots = discover_screenshots(
        date_directory
    )

    coverage_status = (
        classify_screenshot_coverage(
            screenshots
        )
    )

    if coverage_status == "PENDING":
        print(
            f"{target_date} | PENDING | "
            "0 screenshots | 0 API calls"
        )
        return "PENDING"

    if coverage_status == "INVALID":
        print(
            f"{target_date} | INVALID | "
            f"{len(screenshots)} screenshots | "
            "0 API calls"
        )
        return "INVALID"

    content_hash = (
        calculate_content_hash(
            screenshots
        )
    )

    paths = output_paths(target_date)

    canonical_exists = (
        paths["extraction"].exists()
        and paths["metadata"].exists()
    )

    if dry_run:
        print(
            f"{target_date} | READY | "
            "3 screenshots validated | "
            "0 API calls"
        )

        for path in screenshots:
            print(
                f"  {path.name} | "
                f"{path.stat().st_size:,} bytes"
            )

        return "READY"

    if canonical_exists:
        metadata = load_json(
            paths["metadata"]
        )

        if (
            metadata.get("content_hash")
            == content_hash
        ):
            print(
                f"{target_date} | UNCHANGED | "
                "cached extraction reused | "
                "0 API calls"
            )
            return "UNCHANGED"

    if client is None:
        raise RuntimeError(
            "OpenAI client was not initialized."
        )

    original_bytes = sum(
        path.stat().st_size
        for path in screenshots
    )

    prepared_images, optimized_bytes = (
        prepare_images(screenshots)
    )

    print(
        f"{target_date} | IMAGE OPTIMIZATION | "
        f"original={original_bytes:,} bytes | "
        f"optimized={optimized_bytes:,} bytes"
    )

    api_attempts = 0

    try:
        (
            extraction,
            response,
            api_attempts,
        ) = extract_with_ai(
            client,
            prepared_images,
            target_date,
            model,
        )

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is None:
            raise RuntimeError(
                "OpenAI response did not contain "
                "usage data."
            )

        input_tokens = get_usage_value(
            usage,
            "input_tokens",
        )

        output_tokens = get_usage_value(
            usage,
            "output_tokens",
        )

        cached_input_tokens = (
            get_cached_input_tokens(
                usage
            )
        )

        costs = calculate_costs(
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=(
                cached_input_tokens
            ),
            output_tokens=output_tokens,
        )

        validate_screenshot_roles(
            extraction,
            screenshots,
            target_date,
        )

        normalized = normalize_extraction(
            extraction
        )

        normalized = validate_and_reconcile(
            normalized
        )

        warnings = normalized[
            "warnings"
        ]

        status = (
            "API_SUCCESS_REVIEW"
            if warnings
            else "API_SUCCESS_VALID"
        )

        append_usage_record(
            target_date=target_date,
            status=status,
            operation=(
                "screen_time_extraction"
            ),
            model=model,
            api_calls_attempted=(
                api_attempts
            ),
            api_responses_received=1,
            screenshot_count=len(
                screenshots
            ),
            original_screenshot_bytes=(
                original_bytes
            ),
            optimized_image_bytes=(
                optimized_bytes
            ),
            content_hash=content_hash,
            input_tokens=input_tokens,
            cached_input_tokens=(
                cached_input_tokens
            ),
            output_tokens=output_tokens,
        )

        print(
            f"{target_date} | API USAGE | "
            f"attempts={api_attempts} | "
            f"input={input_tokens:,} | "
            f"cached={cached_input_tokens:,} | "
            f"output={output_tokens:,} | "
            f"estimated=${costs['total']:.6f}"
        )

        if warnings:
            print(
                f"{target_date} | "
                f"REVIEW WARNINGS | "
                f"{len(warnings)}"
            )

            for warning in warnings:
                print(
                    f"  WARNING: {warning}"
                )

        metadata = build_metadata(
            target_date=target_date,
            status="canonical",
            content_hash=content_hash,
            model=model,
            screenshots=screenshots,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=(
                cached_input_tokens
            ),
            estimated_cost_usd=(
                costs["total"]
            ),
            api_calls_attempted=(
                api_attempts
            ),
        )

        if not canonical_exists:
            save_canonical(
                target_date,
                normalized,
                metadata,
            )

            if warnings:
                print(
                    f"{target_date} | NEW+REVIEW | "
                    "canonical extraction created "
                    "with deterministic reconciliation"
                )
                return "REVIEW"

            print(
                f"{target_date} | NEW | "
                "AI extraction created"
            )
            return "NEW"

        metadata["status"] = "candidate"

        save_candidate(
            target_date,
            normalized,
            metadata,
        )

        if downstream_output_exists(
            target_date
        ):
            print(
                f"{target_date} | REVIEW | "
                "changed extraction saved as "
                "candidate because downstream "
                "data already exists"
            )
            return "REVIEW"

        if force:
            metadata["status"] = "canonical"

            save_canonical(
                target_date,
                normalized,
                metadata,
            )

            print(
                f"{target_date} | REPLACED | "
                "canonical extraction updated"
            )

            return "REPLACED"

        print(
            f"{target_date} | CHANGED | "
            "candidate extraction created"
        )

        return "CHANGED"

    except Exception as exc:
        append_usage_record(
            target_date=target_date,
            status="API_FAILED",
            operation=(
                "screen_time_extraction"
            ),
            model=model,
            api_calls_attempted=max(
                api_attempts,
                1,
            ),
            api_responses_received=0,
            screenshot_count=len(
                screenshots
            ),
            original_screenshot_bytes=(
                original_bytes
            ),
            optimized_image_bytes=(
                optimized_bytes
            ),
            content_hash=content_hash,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

        raise


def print_usage_summary() -> None:
    """Print current and legacy API usage."""
    current = (
        read_current_usage_summary()
    )

    legacy = (
        read_legacy_usage_summary()
    )

    print()
    print(
        "=== API USAGE LEDGER ==="
    )
    print(
        "Current ledger       : "
        f"{CURRENT_USAGE_LEDGER}"
    )
    print(
        f"API calls attempted  : "
        f"{int(current['attempted']):,}"
    )
    print(
        f"API responses        : "
        f"{int(current['responses']):,}"
    )
    print(
        f"Input tokens         : "
        f"{int(current['input_tokens']):,}"
    )
    print(
        f"Cached input         : "
        f"{int(current['cached_input_tokens']):,}"
    )
    print(
        f"Output tokens        : "
        f"{int(current['output_tokens']):,}"
    )
    print(
        f"Total tokens         : "
        f"{int(current['total_tokens']):,}"
    )
    print(
        f"Estimated current cost: "
        f"${current['cost']:.6f}"
    )

    if legacy["exists"]:
        print()
        print(
            "=== LEGACY API LEDGER ==="
        )
        print(
            "Legacy ledger        : "
            f"{LEGACY_USAGE_LEDGER}"
        )
        print(
            "Legacy backup        : "
            f"{LEGACY_BACKUP_LEDGER}"
        )
        print(
            f"Legacy rows          : "
            f"{legacy['rows']:,}"
        )

        if legacy["cost"] is None:
            print(
                "Legacy cost          : "
                "NOT RELIABLY MERGED"
            )
        else:
            print(
                f"Legacy recorded cost : "
                f"${legacy['cost']:.6f}"
            )

    print()
    print(
        "The current ledger is authoritative "
        "for new API usage."
    )


def main() -> int:
    """Run incremental Apple Screen Time ingestion."""
    args = parse_arguments()

    counts = {
        "PENDING": 0,
        "READY": 0,
        "NEW": 0,
        "UNCHANGED": 0,
        "CHANGED": 0,
        "REVIEW": 0,
        "REPLACED": 0,
        "INVALID": 0,
        "FAILED": 0,
    }

    print(
        "# iPhone Screen Time AI Ingestion"
    )
    print()
    print(
        f"Month : {args.month}"
    )

    if args.dates:
        print(
            "Dates : "
            + ", ".join(args.dates)
        )
    else:
        print(
            "Dates : all available dates"
        )

    print(
        f"Dry   : {args.dry_run}"
    )
    print(
        "Model : "
        f"{args.model if args.model else 'not required'}"
    )
    print()

    try:
        parse_month(args.month)

        preserve_legacy_ledger()

        directories = (
            list_date_directories(
                args.month,
                args.dates,
            )
        )

        client: OpenAI | None = None
        model = ""

        if not args.dry_run:
            model = validate_model(
                args.model
            )
            client = create_client()

        for directory in directories:
            try:
                status = process_date(
                    date_directory=directory,
                    client=client,
                    model=model,
                    force=args.force,
                    dry_run=args.dry_run,
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
            "=== INGESTION SUMMARY ==="
        )

        for status, count in counts.items():
            print(
                f"{status:<12}: {count}"
            )

        if not args.dry_run:
            print_usage_summary()

        if counts["FAILED"] > 0:
            print()
            print(
                "RESULT: IPHONE INGESTION FAILED."
            )
            return 1

        if counts["INVALID"] > 0:
            print()
            print(
                "RESULT: IPHONE INGESTION "
                "REQUIRES REVIEW."
            )
            return 2

        if counts["REVIEW"] > 0:
            print()
            print(
                "RESULT: IPHONE INGESTION "
                "PASSED WITH REVIEW."
            )
            return 0

        print()
        print(
            "RESULT: IPHONE INGESTION PASSED."
        )

        return 0

    except KeyboardInterrupt:
        print()
        print(
            "RESULT: IPHONE INGESTION "
            "CANCELLED."
        )
        return 130

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "RESULT: IPHONE INGESTION FAILED.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())