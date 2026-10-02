"""Test package.

Tests always run against the public, generic settings (device IDs "Laptop"
and "Desktop", generic shared-device rule) so results do not depend on a
developer's git-ignored config/local_settings.json.
"""

import os
from pathlib import Path

os.environ["TIME_ACCOUNTING_SETTINGS"] = str(
    Path(__file__).resolve().parents[1]
    / "config"
    / "local_settings.example.json"
)
