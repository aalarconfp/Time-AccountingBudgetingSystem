# activitywatch_machine.py

from __future__ import annotations

"""Machine-specific ActivityWatch configuration and validation."""

from dataclasses import dataclass
from typing import Final

from aw_client import ActivityWatchClient

from config.settings import DESKTOP_DEVICE, LAPTOP_DEVICE


ACTIVITYWATCH_CLIENT_NAME: Final = "system_tracker_launcher"


@dataclass(frozen=True)
class ActivityWatchMachine:
    """Configuration for one physical machine running ActivityWatch."""

    name: str
    hostname: str
    source: str
    context: str


LAPTOP: Final = ActivityWatchMachine(
    name="laptop",
    hostname=LAPTOP_DEVICE,
    source="asus_laptop",
    context="Work",
)

DESKTOP: Final = ActivityWatchMachine(
    name="desktop",
    hostname=DESKTOP_DEVICE,
    source="desktop",
    context="Personal",
)


def get_machine(name: str) -> ActivityWatchMachine:
    """Return the configured machine profile by name."""
    machines = {
        LAPTOP.name: LAPTOP,
        DESKTOP.name: DESKTOP,
    }

    try:
        return machines[name]
    except KeyError as exc:
        available = ", ".join(sorted(machines))
        raise ValueError(
            f"Unknown ActivityWatch machine '{name}'. "
            f"Available machines: {available}."
        ) from exc


def get_activitywatch_hostname() -> str:
    """Return the hostname reported by the local ActivityWatch server."""
    client = ActivityWatchClient(client_name=ACTIVITYWATCH_CLIENT_NAME)
    info = client.get_info()

    hostname = info.get("hostname")

    if not hostname:
        raise RuntimeError(
            "ActivityWatch server did not report a hostname."
        )

    return str(hostname)


def validate_machine(machine: ActivityWatchMachine) -> str:
    """Validate that the local ActivityWatch server belongs to the machine."""
    detected_hostname = get_activitywatch_hostname()

    if detected_hostname != machine.hostname:
        raise RuntimeError(
            "ActivityWatch machine mismatch.\n"
            f"Expected : {machine.hostname}\n"
            f"Detected : {detected_hostname}\n"
            "Collection aborted to protect device-specific data."
        )

    return detected_hostname