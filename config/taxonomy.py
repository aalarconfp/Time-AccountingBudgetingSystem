"""Shared taxonomy definitions."""

from enum import StrEnum


class Context(StrEnum):
    """High-level areas of life."""

    WORK = "Work"
    PERSONAL = "Personal"
    HEALTH = "Health"
    FAMILY = "Family"
    SOCIAL = "Social"
    EDUCATION = "Education"
    LEISURE = "Leisure"
    SLEEP = "Sleep"
    LIFE = "Life"


class Category(StrEnum):
    """Canonical top-level categories."""

    PRODUCTIVITY_FINANCE = "Productivity & Finance"
    EDUCATION = "Education"
    INFORMATION_READING = "Information & Reading"
    UTILITIES = "Utilities"
    ENTERTAINMENT = "Entertainment"
    SOCIAL_NETWORKING = "Social Networking"
    HEALTH_FITNESS = "Health & Fitness"
    SHOPPING_FOOD = "Shopping & Food"
    CREATIVITY = "Creativity"
    UNCATEGORIZED = "Uncategorized"


SUPPORTED_CONTEXTS = tuple(context.value for context in Context)
SUPPORTED_CATEGORIES = tuple(category.value for category in Category)
