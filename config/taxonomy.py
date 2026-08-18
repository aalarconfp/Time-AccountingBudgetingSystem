# config/taxonomy.py
"""Canonical taxonomy definitions for the System Tracker.

The taxonomy mirrors the current ActivityWatch category hierarchy.

ActivityWatch remains responsible for classifying events. This module
defines the category vocabulary consumed by the downstream System Tracker
pipeline.

The taxonomy may evolve over time as new applications, projects, and
activities are introduced. Historical raw and fact data retain the
classification assigned when they were collected.
"""

from enum import StrEnum


class Context(StrEnum):
    """Canonical contexts for tracked activity."""

    WORK = "Work"
    PERSONAL = "Personal"
    LIFE = "Life"


class Category(StrEnum):
    """Canonical top-level ActivityWatch categories."""

    SOCIAL_NETWORKING = "Social Networking"
    GAMES = "Games"
    ENTERTAINMENT = "Entertainment"
    CREATIVITY = "Creativity"
    PRODUCTIVITY_FINANCE = "Productivity & Finance"
    INFORMATION_READING = "Information & Reading"
    EDUCATION = "Education"
    HEALTH_FITNESS = "Health & Fitness"
    UTILITIES = "Utilities"
    SHOPPING_FOOD = "Shopping & Food"
    TRAVEL = "Travel"
    NEWS = "News"


CATEGORY_SUBCATEGORIES: dict[str, tuple[str, ...]] = {
    Category.SOCIAL_NETWORKING: (
        "Messaging",
        "Meetings",
        "Social Feeds",
        "Career Networking",
    ),
    Category.GAMES: (
        "PC & Steam Games",
    ),
    Category.ENTERTAINMENT: (
        "Video Browsing",
        "Series & Movies",
        "Music",
        "Adult Content",
    ),
    Category.CREATIVITY: (
        "Media Editing",
        "Guitar Practice",
    ),
    Category.PRODUCTIVITY_FINANCE: (
        "Office Tools",
        "Email",
        "Financial Analysis Projects",
        "Personal Brand & Portfolio Site",
        "Business Operations & Invoicing",
        "Banking",
        "Equity Research & Investing",
        "Job Search",
        "Family Business Admin",
        "Time Tracking Tool",
    ),
    Category.INFORMATION_READING: (
        "Podcasts",
        "Personal Reading & News",
    ),
    Category.EDUCATION: (
        "Data & BI Courses",
        "Controller Academy Course",
        "CFI Certification Courses",
        "University Program Admin",
        "Soft Skills Courses",
        "Real Estate Courses",
        "Accounting & Finance Study",
        "AI Tools Learning",
        "External Courses & Bootcamps",
    ),
    Category.HEALTH_FITNESS: (
        "Spiritual & Reflection",
    ),
    Category.UTILITIES: (
        "System Processes",
        "Personal Notes & Meta",
    ),
    Category.SHOPPING_FOOD: (
        "Online Shopping",
        "Entertainment Tickets",
        "Motorcycle & Vehicle Admin",
    ),
    Category.TRAVEL: (
        "Booking & Planning",
    ),
    Category.NEWS: (
        "Civic & Current Affairs",
    ),
}


SUPPORTED_CONTEXTS = tuple(context.value for context in Context)

SUPPORTED_CATEGORIES = tuple(
    category.value
    for category in Category
)


def get_subcategories(
    category: str | Category,
) -> tuple[str, ...]:
    """Return the configured subcategories for a top-level category."""
    category_value = (
        category.value
        if isinstance(category, Category)
        else category
    )

    return CATEGORY_SUBCATEGORIES.get(category_value, ())


def is_supported_category(category: str) -> bool:
    """Return whether a value is a configured top-level category."""
    return category in SUPPORTED_CATEGORIES


def is_supported_subcategory(
    category: str,
    subcategory: str,
) -> bool:
    """Return whether a category/subcategory pair is configured."""
    return subcategory in get_subcategories(category)


def is_supported_category_path(
    category: str,
    subcategory: str = "",
) -> bool:
    """Return whether a category hierarchy is configured."""
    if not is_supported_category(category):
        return False

    if not subcategory:
        return True

    return is_supported_subcategory(
        category,
        subcategory,
    )


def get_category_path(
    category: str,
    subcategory: str = "",
) -> str:
    """Return a canonical category path."""
    if subcategory:
        return f"{category} > {subcategory}"

    return category