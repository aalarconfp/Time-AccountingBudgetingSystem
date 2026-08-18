# FILE: iphone_screen_time_ingest.py

"""AI-assisted Apple Screen Time screenshot ingestion.

Each completed date should contain exactly three screenshots.

The original screenshots remain untouched. Before an API request, the
screenshots are resized into temporary optimized images to reduce image
input-token usage.

The AI performs evidence extraction only. Master-taxonomy classification
happens downstream.

API requests and their token usage are recorded in:

    output/Analysis/API/OpenAI_Usage.csv

Canonical extractions are stored in:

    output/Raw/AppleScreenTime/iPhone/YYYY-MM/YYYY-MM-DD/

A date with no screenshots is PENDING and requires no API call.

A date with exactly three supported images is READY.

A date with any other number of supported images is INVALID.

If screenshots change after canonical data already exists, the new
extraction is saved as a candidate. Existing downstream data is never
silently overwritten.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI


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

API_USAGE_OUTPUT = (
    PROJECT_ROOT
    / "output"
    / "Analysis"
    / "API"
    / "OpenAI_Usage.csv"
)

SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "")

# Current API pricing for gpt-4o-mini.
MODEL_PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
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

# Screenshots are optimized only for transmission.
# Originals remain untouched on disk.
OPTIMIZED_MAX_DIMENSION = 1600
OPTIMIZED_JPEG_QUALITY = 88

USAGE_FIELDS = (
    "timestamp_utc",
    "date",
    "status",
    "operation",
    "model",
    "api_calls_attempted",
    "api_response_received",
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
        "total_screen_time_sec": {
            "type": "number",
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
                    "duration_sec": {
                        "type": "number",
                    },
                    "duration_display": {
                        "type": "string",
                    },
                },
                "required": [
                    "apple_category",
                    "duration_sec",
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
                    "duration_sec": {
                        "type": "number",
                    },
                    "duration_display": {
                        "type": "string",
                    },
                },
                "required": [
                    "app",
                    "duration_sec",
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
        "total_screen_time_sec",
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

Filenames are arbitrary. Do NOT infer screenshot roles from filenames.

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

TOTAL:
- Extract the daily Screen Time total.
- Convert the displayed duration to seconds.

CATEGORIES:
- Extract every visible Apple Screen Time category and duration.
- Preserve Apple's category names exactly as visible.
- Convert durations to seconds.

SOCIAL:
- Extract every visible application and duration.
- Determine whether the visible application list appears complete.
- If the list is truncated or completeness cannot be established,
  set social_detail_complete to false.
- Convert durations to seconds.

IMPORTANT ACCOUNTING RULE:

Social application durations are detail belonging to the Social
category. They must NOT be added on top of category totals.

Do NOT add category totals and application totals together.

This stage performs EVIDENCE EXTRACTION ONLY.

Do NOT map applications or Apple categories into the project's master
taxonomy.

Do NOT invent values.

Do not estimate a duration from chart size when readable text exists.

If a value is unclear, use the most defensible visible value and add a
warning.

If screenshots appear to conflict, preserve the visible evidence and
add a warning.

If a list appears truncated, preserve the visible entries and add a
warning.

The folder date is authoritative for the expected calendar date.

Return ONLY structured JSON matching the supplied schema.
"""


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract Apple Screen Time screenshots with AI."
    )

    parser.add_argument(
        "--month",
        required=True,
        help="Month in YYYY-MM format.",
    )

    parser.add_argument(
        "--date",
        help="Process one date only.",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenAI model. Can also be supplied through OPENAI_MODEL.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace canonical extraction after successful processing.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate screenshot coverage without calling OpenAI.",
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
    """Require a configured model."""
    model = model.strip()

    if not model:
        raise RuntimeError(
            "No OpenAI model configured. "
            "Set OPENAI_MODEL or pass --model."
        )

    if model not in MODEL_PRICING_USD_PER_MILLION:
        raise RuntimeError(
            f"No API pricing configuration exists for '{model}'. "
            "Add current pricing before using this model."
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
    target_date: str | None,
) -> list[Path]:
    """Return date folders to inspect."""
    parse_month(month)

    month_directory = SCREEN_TIME_INPUT / month

    if not month_directory.exists():
        raise FileNotFoundError(
            f"Missing Screen Time month directory: {month_directory}"
        )

    if target_date:
        parsed = parse_date(target_date)

        if parsed.strftime("%Y-%m") != month:
            raise ValueError(
                f"{target_date} is outside {month}."
            )

        directory = month_directory / target_date

        if not directory.exists():
            raise FileNotFoundError(
                f"Missing Screen Time date directory: {directory}"
            )

        return [directory]

    return sorted(
        directory
        for directory in month_directory.iterdir()
        if directory.is_dir()
        and directory.name[:7] == month
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
    """Classify a date folder by screenshot count."""
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
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())

    return digest.hexdigest()


def calculate_file_hash(path: Path) -> str:
    """Return a SHA-256 hash for one file."""
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def output_paths(
    target_date: str,
) -> dict[str, Path]:
    """Return output artifact paths."""
    directory = (
        RAW_OUTPUT
        / target_date[:7]
        / target_date
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return {
        "extraction": directory / "AI_Extraction.json",
        "metadata": directory / "AI_Metadata.json",
        "candidate_extraction": (
            directory / "AI_Extraction_Candidate.json"
        ),
        "candidate_metadata": (
            directory / "AI_Metadata_Candidate.json"
        ),
    }


def load_json(path: Path) -> dict[str, Any]:
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

    return fact_path.exists() or daily_path.exists()


def calculate_costs(
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> dict[str, float]:
    """Calculate estimated API costs."""
    pricing = MODEL_PRICING_USD_PER_MILLION[model]

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


def ensure_usage_ledger() -> None:
    """Create the API usage ledger if necessary."""
    API_USAGE_OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if API_USAGE_OUTPUT.exists():
        return

    with API_USAGE_OUTPUT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=USAGE_FIELDS,
        )
        writer.writeheader()


def append_usage_record(
    *,
    target_date: str,
    status: str,
    operation: str,
    model: str,
    api_calls_attempted: int,
    api_response_received: int,
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
    """Append one auditable API usage record."""
    ensure_usage_ledger()

    total_tokens = (
        input_tokens
        + output_tokens
    )

    costs = calculate_costs(
        model,
        input_tokens,
        cached_input_tokens,
        output_tokens,
    )

    row = {
        "timestamp_utc": (
            datetime.now(timezone.utc)
            .isoformat()
        ),
        "date": target_date,
        "status": status,
        "operation": operation,
        "model": model,
        "api_calls_attempted": api_calls_attempted,
        "api_response_received": api_response_received,
        "screenshot_count": screenshot_count,
        "original_screenshot_bytes": (
            original_screenshot_bytes
        ),
        "optimized_image_bytes": (
            optimized_image_bytes
        ),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
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

    with API_USAGE_OUTPUT.open(
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


def read_usage_summary() -> dict[str, float]:
    """Read cumulative API usage from the ledger."""
    if not API_USAGE_OUTPUT.exists():
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

    with API_USAGE_OUTPUT.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)

        for row in reader:
            attempted += int(
                row.get("api_calls_attempted") or 0
            )

            responses += int(
                row.get("api_response_received") or 0
            )

            input_tokens += int(
                row.get("input_tokens") or 0
            )

            cached_input_tokens += int(
                row.get("cached_input_tokens") or 0
            )

            output_tokens += int(
                row.get("output_tokens") or 0
            )

            total_tokens += int(
                row.get("total_tokens") or 0
            )

            cost += float(
                row.get("estimated_total_cost_usd")
                or 0
            )

    return {
        "attempted": attempted,
        "responses": responses,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
    }


def optimize_image(
    path: Path,
) -> tuple[bytes, str]:
    """Resize an image for API transmission."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for screenshot optimization. "
            "Install it with: python -m pip install Pillow"
        ) from exc

    with Image.open(path) as image:
        image = image.convert("RGB")

        width, height = image.size
        largest_dimension = max(width, height)

        if largest_dimension > OPTIMIZED_MAX_DIMENSION:
            scale = (
                OPTIMIZED_MAX_DIMENSION
                / largest_dimension
            )

            new_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
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
    """Convert optimized image bytes to a data URL."""
    encoded = base64.b64encode(
        image_bytes
    ).decode("ascii")

    return (
        f"data:{media_type};base64,{encoded}"
    )


def prepare_images(
    screenshots: tuple[Path, ...],
) -> tuple[list[tuple[Path, bytes, str]], int]:
    """Prepare optimized images for one API request."""
    prepared: list[
        tuple[Path, bytes, str]
    ] = []

    total_bytes = 0

    for path in screenshots:
        image_bytes, media_type = optimize_image(
            path
        )

        prepared.append(
            (
                path,
                image_bytes,
                media_type,
            )
        )

        total_bytes += len(image_bytes)

    return prepared, total_bytes


def get_usage_value(
    usage: Any,
    attribute: str,
    default: int = 0,
) -> int:
    """Read an integer usage value from an SDK usage object."""
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
    """Read cached input token usage when available."""
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


def extract_with_ai(
    client: OpenAI,
    prepared_images: list[tuple[Path, bytes, str]],
    target_date: str,
    model: str,
) -> tuple[dict[str, Any], Any]:
    """Send optimized screenshots to the vision model."""
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

    for path, image_bytes, media_type in prepared_images:
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"Original filename: {path.name}"
                ),
            }
        )

        content.append(
            {
                "type": "input_image",
                "image_url": image_bytes_to_data_url(
                    image_bytes,
                    media_type,
                ),
                "detail": "high",
            }
        )

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
                "name": "apple_screen_time_extraction",
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

    return extraction, response


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
            "AI did not return exactly three screenshot roles."
        )

    actual_filenames = {
        str(entry["filename"])
        for entry in role_entries
    }

    if actual_filenames != expected_filenames:
        raise ValueError(
            "AI screenshot filenames do not match "
            "the supplied files."
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
                "Screenshot confidence must be between 0 and 1."
            )


def validate_extraction_values(
    extraction: dict[str, Any],
) -> list[str]:
    """Validate values and return non-fatal warnings."""
    warnings = [
        str(warning)
        for warning in extraction.get(
            "warnings",
            [],
        )
    ]

    total = float(
        extraction["total_screen_time_sec"]
    )

    if total < 0:
        raise ValueError(
            "Total Screen Time cannot be negative."
        )

    category_total = 0.0

    for category in extraction["categories"]:
        duration = float(
            category["duration_sec"]
        )

        if duration < 0:
            raise ValueError(
                "Category duration cannot be negative."
            )

        category_total += duration

    if category_total <= 0:
        raise ValueError(
            "No positive category time was extracted."
        )

    if category_total > total + 120:
        warnings.append(
            "Visible category total exceeds total Screen Time "
            "by more than two minutes."
        )

    if total > category_total + 120:
        warnings.append(
            "Visible category total is more than two minutes "
            "below total Screen Time."
        )

    social_category = next(
        (
            float(category["duration_sec"])
            for category in extraction["categories"]
            if category["apple_category"].strip().lower()
            == "social"
        ),
        None,
    )

    if social_category is not None:
        social_total = sum(
            float(app["duration_sec"])
            for app in extraction["social_apps"]
        )

        if (
            extraction["social_detail_complete"]
            and social_total > social_category + 120
        ):
            warnings.append(
                "Visible Social app detail exceeds the "
                "Social category total. Preserved for review."
            )

        if (
            extraction["social_detail_complete"]
            and social_category > social_total + 120
        ):
            warnings.append(
                "Visible Social app detail does not fully "
                "reconcile to the Social category total."
            )

    extraction["warnings"] = list(
        dict.fromkeys(warnings)
    )

    return extraction["warnings"]


def save_canonical(
    target_date: str,
    extraction: dict[str, Any],
    content_hash: str,
    model: str,
    screenshots: tuple[Path, ...],
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    estimated_cost_usd: float,
) -> None:
    """Save a canonical extraction and metadata."""
    paths = output_paths(target_date)

    paths["extraction"].write_text(
        json.dumps(
            extraction,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    paths["metadata"].write_text(
        json.dumps(
            {
                "date": target_date,
                "status": "canonical",
                "content_hash": content_hash,
                "model": model,
                "usage": {
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
                        "sha256": calculate_file_hash(path),
                    }
                    for path in screenshots
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_candidate(
    target_date: str,
    extraction: dict[str, Any],
    content_hash: str,
    model: str,
    screenshots: tuple[Path, ...],
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    estimated_cost_usd: float,
) -> None:
    """Save a changed extraction as a review candidate."""
    paths = output_paths(target_date)

    paths["candidate_extraction"].write_text(
        json.dumps(
            extraction,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    paths["candidate_metadata"].write_text(
        json.dumps(
            {
                "date": target_date,
                "status": "candidate",
                "content_hash": content_hash,
                "model": model,
                "usage": {
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
                        "sha256": calculate_file_hash(path),
                    }
                    for path in screenshots
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def process_date(
    date_directory: Path,
    client: OpenAI | None,
    model: str,
    force: bool,
    dry_run: bool,
) -> str:
    """Validate or process one date."""
    target_date = date_directory.name

    screenshots = discover_screenshots(
        date_directory
    )

    coverage_status = classify_screenshot_coverage(
        screenshots
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

    content_hash = calculate_content_hash(
        screenshots
    )

    paths = output_paths(target_date)

    canonical_exists = (
        paths["extraction"].exists()
        and paths["metadata"].exists()
    )

    if dry_run:
        print(
            f"{target_date} | READY | "
            "3 screenshots validated | 0 API calls"
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

        if metadata.get("content_hash") == content_hash:
            print(
                f"{target_date} | UNCHANGED | "
                "cached extraction reused | 0 API calls"
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

    api_response_received = False
    extraction: dict[str, Any] | None = None
    response: Any = None

    try:
        extraction, response = extract_with_ai(
            client,
            prepared_images,
            target_date,
            model,
        )

        api_response_received = True

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is None:
            raise RuntimeError(
                "OpenAI response did not contain usage data."
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
            get_cached_input_tokens(usage)
        )

        costs = calculate_costs(
            model,
            input_tokens,
            cached_input_tokens,
            output_tokens,
        )

        warnings: list[str] = []

        try:
            validate_screenshot_roles(
                extraction,
                screenshots,
                target_date,
            )

            warnings.extend(
                validate_extraction_values(
                    extraction
                )
            )

        except ValueError as validation_error:
            warnings.append(
                "Extraction validation warning: "
                + str(validation_error)
            )

        extraction["warnings"] = list(
            dict.fromkeys(
                [
                    *extraction.get(
                        "warnings",
                        [],
                    ),
                    *warnings,
                ]
            )
        )

        if warnings:
            extraction_status = "API_SUCCESS_REVIEW"
        else:
            extraction_status = "API_SUCCESS_VALID"

        append_usage_record(
            target_date=target_date,
            status=extraction_status,
            operation="screen_time_extraction",
            model=model,
            api_calls_attempted=1,
            api_response_received=1,
            screenshot_count=len(screenshots),
            original_screenshot_bytes=original_bytes,
            optimized_image_bytes=optimized_bytes,
            content_hash=content_hash,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )

        print(
            f"{target_date} | API USAGE | "
            f"input={input_tokens:,} | "
            f"cached={cached_input_tokens:,} | "
            f"output={output_tokens:,} | "
            f"estimated=${costs['total']:.6f}"
        )

        if warnings:
            print(
                f"{target_date} | REVIEW WARNINGS | "
                f"{len(warnings)}"
            )

            for warning in warnings:
                print(
                    f"  WARNING: {warning}"
                )

        if not canonical_exists:
            save_canonical(
                target_date,
                extraction,
                content_hash,
                model,
                screenshots,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=(
                    cached_input_tokens
                ),
                estimated_cost_usd=(
                    costs["total"]
                ),
            )

            if warnings:
                print(
                    f"{target_date} | NEW+REVIEW | "
                    "canonical extraction created "
                    "with warnings"
                )
                return "REVIEW"

            print(
                f"{target_date} | NEW | "
                "AI extraction created"
            )
            return "NEW"

        if (
            not force
            and downstream_output_exists(target_date)
        ):
            save_candidate(
                target_date,
                extraction,
                content_hash,
                model,
                screenshots,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=(
                    cached_input_tokens
                ),
                estimated_cost_usd=(
                    costs["total"]
                ),
            )

            print(
                f"{target_date} | REVIEW | "
                "screenshots changed; canonical data preserved"
            )

            return "REVIEW"

        if not force:
            save_candidate(
                target_date,
                extraction,
                content_hash,
                model,
                screenshots,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=(
                    cached_input_tokens
                ),
                estimated_cost_usd=(
                    costs["total"]
                ),
            )

            print(
                f"{target_date} | CHANGED | "
                "candidate extraction created"
            )

            return "CHANGED"

        save_canonical(
            target_date,
            extraction,
            content_hash,
            model,
            screenshots,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=(
                cached_input_tokens
            ),
            estimated_cost_usd=(
                costs["total"]
            ),
        )

        print(
            f"{target_date} | REPLACED | "
            "canonical extraction updated"
        )

        return "REPLACED"

    except Exception as exc:
        if not api_response_received:
            append_usage_record(
                target_date=target_date,
                status="API_FAILED",
                operation="screen_time_extraction",
                model=model,
                api_calls_attempted=1,
                api_response_received=0,
                screenshot_count=len(screenshots),
                original_screenshot_bytes=original_bytes,
                optimized_image_bytes=optimized_bytes,
                content_hash=content_hash,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        raise


def print_usage_summary() -> None:
    """Print cumulative API usage."""
    summary = read_usage_summary()

    print()
    print("=== API USAGE LEDGER ===")
    print(
        f"API calls attempted : "
        f"{summary['attempted']:,}"
    )
    print(
        f"API responses       : "
        f"{summary['responses']:,}"
    )
    print(
        f"Input tokens        : "
        f"{summary['input_tokens']:,}"
    )
    print(
        f"Cached input        : "
        f"{summary['cached_input_tokens']:,}"
    )
    print(
        f"Output tokens       : "
        f"{summary['output_tokens']:,}"
    )
    print(
        f"Total tokens        : "
        f"{summary['total_tokens']:,}"
    )
    print(
        f"Estimated cost      : "
        f"${summary['cost']:.6f}"
    )
    print(
        f"Ledger              : "
        f"{API_USAGE_OUTPUT}"
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

    print("# iPhone Screen Time AI Ingestion")
    print()
    print(f"Month : {args.month}")
    print(
        f"Date  : {args.date or 'all available dates'}"
    )
    print(f"Dry   : {args.dry_run}")
    print(
        f"Model : "
        f"{args.model if args.model else 'not required'}"
    )
    print()

    try:
        parse_month(args.month)

        directories = list_date_directories(
            args.month,
            args.date,
        )

        client: OpenAI | None = None
        model = ""

        if not args.dry_run:
            model = validate_model(args.model)
            client = create_client()

        for directory in directories:
            try:
                status = process_date(
                    directory,
                    client,
                    model,
                    args.force,
                    args.dry_run,
                )

                counts[status] += 1

            except Exception as exc:
                counts["FAILED"] += 1

                print(
                    f"{directory.name} | FAILED | "
                    f"{type(exc).__name__}: {exc}"
                )

        print()
        print("=== INGESTION SUMMARY ===")

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
            print(
                "At least one date could not be processed."
            )
            return 1

        if counts["INVALID"] > 0:
            print()
            print(
                "RESULT: IPHONE INGESTION REQUIRES REVIEW."
            )
            print(
                "At least one date has an incomplete or "
                "unexpected screenshot set."
            )
            return 2

        if counts["REVIEW"] > 0:
            print()
            print(
                "RESULT: IPHONE INGESTION PASSED WITH REVIEW."
            )
            print(
                "Evidence was preserved, but at least one "
                "date contains a review warning."
            )
            return 0

        print()
        print(
            "RESULT: IPHONE INGESTION PASSED."
        )

        return 0

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