"""Unit tests for config.settings and the shared-device attribution rule."""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config.settings as settings  # noqa: E402
import config.sources as sources  # noqa: E402
import desktop_export_contract as contract  # noqa: E402
import final_analysis as fa  # noqa: E402

DAY = date(2026, 9, 1)
RULE = fa.SHARED_DEVICE_RULE
TOKEN = "Shared Device: Secondary User / not my time"


def record(source, device, category, minutes, activity=None):
    return fa.Record(
        date=DAY,
        source=source,
        device=device,
        activity=activity or category,
        category=category,
        subcategory=category,
        duration_sec=minutes * 60.0,
        allocation_type="Observed",
    )


def adjustment(minutes, reason=TOKEN, category="Offline Work Tracking"):
    return fa.HabitAdjustment(
        date=DAY,
        category=category,
        adjustment_sec=minutes * 60.0,
        reason=reason,
    )


class SettingsTests(unittest.TestCase):
    def write(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "local_settings.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_defaults_are_generic(self):
        loaded = settings.load_settings(Path("does-not-exist.json"))
        self.assertEqual(loaded.laptop_device, "Laptop")
        self.assertEqual(loaded.desktop_device, "Desktop")
        rule = loaded.shared_device_attribution
        self.assertEqual(rule.target_device, "Desktop")
        self.assertEqual(rule.target_device_key, "desktop")

    def test_local_file_overrides_devices_and_rule(self):
        path = self.write({
            "devices": {"laptop": "WorkLaptop", "desktop": "HomePC"},
            "shared_device_attribution": {"reason_tokens": ["guest user"]},
        })
        loaded = settings.load_settings(path)
        self.assertEqual(loaded.laptop_device, "WorkLaptop")
        self.assertEqual(loaded.desktop_device, "HomePC")
        rule = loaded.shared_device_attribution
        self.assertEqual(rule.target_device, "HomePC")
        self.assertTrue(rule.matches_reason("GUEST USER on the pc"))
        self.assertFalse(rule.matches_reason("shared device: secondary user"))
        # Unspecified rule fields keep the public defaults.
        self.assertEqual(rule.habit_category, "Offline Work Tracking")

    def test_unknown_target_device_is_rejected(self):
        path = self.write({"shared_device_attribution": {"target_device": "tablet"}})
        with self.assertRaises(ValueError):
            settings.load_settings(path)

    def test_sources_and_contract_use_configured_devices(self):
        self.assertEqual(sources.ASUS_LAPTOP.device, settings.LAPTOP_DEVICE)
        self.assertEqual(sources.DESKTOP.device, settings.DESKTOP_DEVICE)
        self.assertNotEqual(sources.ASUS_LAPTOP.device, sources.DESKTOP.device)
        # Source != Device: both devices belong to the ActivityWatch source.
        self.assertEqual(sources.ASUS_LAPTOP.source, sources.DESKTOP.source)
        self.assertEqual(contract.DEVICE_HOSTNAME, settings.DESKTOP_DEVICE)
        self.assertTrue(contract.RAW_SUBPATH.endswith("/" + settings.DESKTOP_DEVICE))


class SharedDeviceRuleTests(unittest.TestCase):
    def test_rule_identifies_secondary_user_adjustments(self):
        self.assertTrue(fa.is_shared_device_adjustment(adjustment(-60)))
        self.assertTrue(fa.is_shared_device_adjustment(adjustment(-60, reason=TOKEN.upper())))
        # Positive, other category or other reason: not a rule hit.
        self.assertFalse(fa.is_shared_device_adjustment(adjustment(60)))
        self.assertFalse(fa.is_shared_device_adjustment(adjustment(-60, category="Reading")))
        self.assertFalse(fa.is_shared_device_adjustment(adjustment(-60, reason="Overstated")))

    def test_rule_redirects_instead_of_subtracting_habit(self):
        habit = record(fa.HABIT_SOURCE, "Habit", "Offline Work Tracking", 120)
        result, audit, redirected = fa.apply_habit_adjustments([habit], [adjustment(-60)])
        self.assertEqual(result, [habit])
        self.assertEqual(redirected, [adjustment(-60)])
        self.assertEqual(audit[0]["Status"], "REDIRECTED_TO_ACTIVITYWATCH")

    def test_removal_only_hits_shared_device_uncategorized(self):
        laptop = record(fa.ACTIVITYWATCH_SOURCE, "Laptop", "Uncategorized", 100)
        desktop_uncat = record(fa.ACTIVITYWATCH_SOURCE, "Desktop", "Uncategorized", 100)
        desktop_cat = record(fa.ACTIVITYWATCH_SOURCE, "Desktop", "Games", 100)
        phone = record(fa.APPLE_SCREEN_TIME_SOURCE, "AppleScreenTime", "Uncategorized", 100)
        records = [laptop, desktop_uncat, desktop_cat, phone]

        result, audit = fa.apply_shared_device_attribution(records, [adjustment(-30)])

        self.assertEqual(result[0], laptop)
        self.assertAlmostEqual(result[1].duration_sec, 70 * 60.0)
        self.assertEqual(result[1].allocation_type, RULE.allocation_type)
        self.assertEqual(result[2], desktop_cat)
        self.assertEqual(result[3], phone)
        row = audit[0]
        self.assertEqual(row["Device_Target"], "Desktop")
        self.assertEqual((row["Requested_min"], row["Applied_min"], row["Unapplied_min"]), (30.0, 30.0, 0.0))
        self.assertEqual(row["Status"], "APPLIED")
        # Accounting stays consistent: total drops by exactly the applied time.
        before = sum(r.duration_sec for r in records)
        after = sum(r.duration_sec for r in result)
        self.assertAlmostEqual(before - after, 30 * 60.0)

    def test_removal_is_capped_at_available_time(self):
        desktop_uncat = record(fa.ACTIVITYWATCH_SOURCE, "Desktop", "Uncategorized", 20)
        result, audit = fa.apply_shared_device_attribution([desktop_uncat], [adjustment(-50)])
        self.assertAlmostEqual(result[0].duration_sec, 0.0)
        self.assertEqual(audit[0]["Status"], "CAPPED_AT_AVAILABLE_TIME")
        self.assertEqual((audit[0]["Applied_min"], audit[0]["Unapplied_min"]), (20.0, 30.0))

    def test_laptop_and_desktop_stay_separate_devices(self):
        laptop = record(fa.ACTIVITYWATCH_SOURCE, "Laptop", "Games", 45)
        desktop = record(fa.ACTIVITYWATCH_SOURCE, "Desktop", "Games", 15)
        self.assertFalse(fa.is_shared_device_record(laptop))
        self.assertTrue(fa.is_shared_device_record(desktop))
        totals = {}
        for item in (laptop, desktop):
            totals[item.device] = totals.get(item.device, 0.0) + item.duration_sec
        self.assertEqual(set(totals), {"Laptop", "Desktop"})
        self.assertAlmostEqual(sum(totals.values()), 60 * 60.0)


if __name__ == "__main__":
    unittest.main()
