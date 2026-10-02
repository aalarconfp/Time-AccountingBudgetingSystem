# config/settings.py

"""User-specific settings: device identities and shared-device attribution.

Public defaults are generic. Each installation can override them in a
git-ignored JSON file, ``config/local_settings.json`` (see
``config/local_settings.example.json``), or in the file named by the
``TIME_ACCOUNTING_SETTINGS`` environment variable.

Device IDs are functional: they are the ActivityWatch hostname of each
machine and the directory name under ``output/Raw|Fact|Daily/.../`` where
that device's data is stored. Change them only together with the data.

This module is stdlib-only so the desktop import contract can use it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SETTINGS_ENV_VAR = "TIME_ACCOUNTING_SETTINGS"

LOCAL_SETTINGS_PATH = (
    Path(__file__).resolve().parent / "local_settings.json"
)


@dataclass(frozen=True)
class SharedDeviceAttributionRule:
    """Exclude time a secondary user spent on a shared device.

    A negative Habit manual adjustment whose category matches
    ``habit_category`` and whose reason contains any of ``reason_tokens``
    (case-insensitive) is not subtracted from Habit. The time is removed
    instead from ActivityWatch Uncategorized records on ``target_device``
    (the device ID configured under ``target_device_key``).
    """

    habit_category: str
    reason_tokens: tuple[str, ...]
    target_device_key: str
    target_device: str
    allocation_type: str

    def matches_reason(self, reason: str) -> bool:
        text = reason.lower()
        return any(
            token.lower() in text
            for token in self.reason_tokens
        )


@dataclass(frozen=True)
class Settings:
    laptop_device: str
    desktop_device: str
    shared_device_attribution: SharedDeviceAttributionRule


DEFAULTS: dict[str, Any] = {
    "devices": {
        "laptop": "Laptop",
        "desktop": "Desktop",
    },
    "shared_device_attribution": {
        "habit_category": "Offline Work Tracking",
        "reason_tokens": ["shared device: secondary user"],
        "target_device": "desktop",
        "allocation_type": "Shared Device Attribution Removal",
    },
}


def settings_path() -> Path:
    """Return the settings file in effect (it may not exist)."""
    override = os.environ.get(SETTINGS_ENV_VAR)
    return Path(override) if override else LOCAL_SETTINGS_PATH


def load_settings(path: Path | None = None) -> Settings:
    """Merge the optional local settings file over the public defaults."""
    path = path or settings_path()

    local: dict[str, Any] = {}
    if path.is_file():
        local = json.loads(path.read_text(encoding="utf-8"))

    devices = {
        **DEFAULTS["devices"],
        **local.get("devices", {}),
    }
    rule = {
        **DEFAULTS["shared_device_attribution"],
        **local.get("shared_device_attribution", {}),
    }

    target_key = rule["target_device"]
    if target_key not in devices:
        raise ValueError(
            f"{path}: shared_device_attribution.target_device "
            f"{target_key!r} is not one of {sorted(devices)}."
        )

    return Settings(
        laptop_device=devices["laptop"],
        desktop_device=devices["desktop"],
        shared_device_attribution=SharedDeviceAttributionRule(
            habit_category=rule["habit_category"],
            reason_tokens=tuple(rule["reason_tokens"]),
            target_device_key=target_key,
            target_device=devices[target_key],
            allocation_type=rule["allocation_type"],
        ),
    )


SETTINGS = load_settings()

LAPTOP_DEVICE = SETTINGS.laptop_device
DESKTOP_DEVICE = SETTINGS.desktop_device
SHARED_DEVICE_RULE = SETTINGS.shared_device_attribution
