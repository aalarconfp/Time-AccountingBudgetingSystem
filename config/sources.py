# config/sources.py

"""Canonical source and device definitions."""

from dataclasses import dataclass
from enum import StrEnum

from config.settings import DESKTOP_DEVICE, LAPTOP_DEVICE


class ObservationType(StrEnum):
    """Types of observations entering the tracking system."""

    DEVICE_TIME = "DeviceTime"
    PHONE_TIME = "PhoneTime"
    LIFE_ACTIVITY = "LifeActivity"


class SourceType(StrEnum):
    """Supported data sources."""

    ACTIVITYWATCH = "ActivityWatch"
    APPLE_SCREEN_TIME = "AppleScreenTime"
    HABIT = "Habit"


@dataclass(frozen=True)
class SourceDefinition:
    """Describe a source and the observations it produces."""

    source: SourceType
    observation_type: ObservationType
    device: str | None
    context: str
    description: str


ASUS_LAPTOP = SourceDefinition(
    source=SourceType.ACTIVITYWATCH,
    observation_type=ObservationType.DEVICE_TIME,
    device=LAPTOP_DEVICE,
    context="Work",
    description="ActivityWatch data from the primary work/project laptop.",
)

DESKTOP = SourceDefinition(
    source=SourceType.ACTIVITYWATCH,
    observation_type=ObservationType.DEVICE_TIME,
    device=DESKTOP_DEVICE,
    context="Personal",
    description="ActivityWatch data from the personal desktop.",
)

IPHONE = SourceDefinition(
    source=SourceType.APPLE_SCREEN_TIME,
    observation_type=ObservationType.PHONE_TIME,
    device="iPhone",
    context="Personal",
    description="Apple Screen Time data extracted from iPhone reports or screenshots.",
)

HABIT = SourceDefinition(
    source=SourceType.HABIT,
    observation_type=ObservationType.LIFE_ACTIVITY,
    device=None,
    context="Life",
    description="Manually recorded off-device activities from Habit.",
)


SOURCE_DEFINITIONS = {
    "asus_laptop": ASUS_LAPTOP,
    "desktop": DESKTOP,
    "iphone": IPHONE,
    "habit": HABIT,
}


def get_source_definition(name: str) -> SourceDefinition:
    """Return a configured source by name."""
    try:
        return SOURCE_DEFINITIONS[name]
    except KeyError as exc:
        available = ", ".join(sorted(SOURCE_DEFINITIONS))
        raise ValueError(
            f"Unknown source '{name}'. Available sources: {available}"
        ) from exc