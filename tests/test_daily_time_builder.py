"""Unit tests for daily_time_builder (stdlib unittest).

The iPhone source must be refused so that the generic seven-column builder
can never overwrite iPhone Daily_Time provenance; laptop and desktop
behaviour is unchanged.
"""

import csv
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_time_builder as dtb  # noqa: E402
from config.sources import get_source_definition  # noqa: E402

FACT_HEADER = ("Fact_Time_ID,Date,Start,End,Duration_sec,Device,Source,Source_Bucket,"
               "Source_Event_ID,App,Window_Title,Category,Subcategory\n")
DAY = date(2026, 9, 1)


def fact_row(device: str, event: int, seconds: float, category: str, subcategory: str) -> str:
    return (f"{device}:ActivityWatch:{event},{DAY},s,e,{seconds},{device},ActivityWatch,b,"
            f"{event},app.exe,,{category},{subcategory}\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.fact_root = root / "Fact" / "Time"
        self.daily_root = root / "Daily"
        self.patches = [
            mock.patch.object(dtb, "FACT_TIME_ROOT", self.fact_root),
            mock.patch.object(dtb, "DAILY_ROOT", self.daily_root),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_fact(self, source_name: str, body: str) -> Path:
        source = get_source_definition(source_name)
        path = dtb.get_fact_time_path(source, DAY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FACT_HEADER + body, encoding="utf-8")
        return path

    def build(self, source_name: str):
        with redirect_stdout(io.StringIO()):
            return dtb.build_date(get_source_definition(source_name), DAY)

    def read_daily(self, source_name: str) -> list[dict[str, str]]:
        path = dtb.get_daily_time_path(get_source_definition(source_name), DAY)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def run_main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["daily_time_builder.py", *argv]), redirect_stdout(out):
            code = dtb.main()
        return code, out.getvalue()


class TestIphoneRefused(Base):
    def setUp(self):
        super().setUp()
        source = get_source_definition("iphone")
        self.fact_path = dtb.get_fact_time_path(source, DAY)
        self.fact_path.parent.mkdir(parents=True, exist_ok=True)
        self.fact_path.write_text(
            "Date,Source,Category,Subcategory,App,Duration_sec,Event_Count,Allocation_Type,"
            "Evidence_Type,Evidence_Source\n"
            f"{DAY},iphone,Utilities,Utilities,,600,0,Estimated,Opal_Calibrated_Estimate,x\n",
            encoding="utf-8",
        )
        self.daily_path = dtb.get_daily_time_path(source, DAY)
        self.daily_path.parent.mkdir(parents=True, exist_ok=True)
        self.daily_path.write_text(
            "Date,Source,Category,Subcategory,Duration_sec,Event_Count,Allocation_Type,"
            "Evidence_Type,Evidence_Source\n"
            f"{DAY},iphone,Utilities,Utilities,600,0,Estimated,Opal_Calibrated_Estimate,x\n",
            encoding="utf-8",
        )
        self.before = hashlib.sha256(self.daily_path.read_bytes()).hexdigest()

    def assert_untouched(self):
        self.assertEqual(hashlib.sha256(self.daily_path.read_bytes()).hexdigest(), self.before)
        self.assertEqual(sorted(p.name for p in self.daily_path.parent.iterdir()),
                         [self.daily_path.name])

    def test_cli_refuses_iphone_with_clear_error(self):
        code, output = self.run_main("--source", "iphone", "--date", DAY.isoformat())
        self.assertEqual(code, 1)
        self.assertIn("iPhone Daily_Time must not be built by daily_time_builder.py", output)
        self.assertIn("iphone_screen_time_builder.py", output)
        self.assertNotIn("Fact_Time input", output)  # refused before any date was processed
        self.assert_untouched()

    def test_cli_refuses_iphone_range(self):
        code, _ = self.run_main("--source", "iphone",
                                "--start-date", "2026-09-01", "--end-date", "2026-09-02")
        self.assertEqual(code, 1)
        self.assert_untouched()

    def test_build_date_refuses_iphone_programmatically(self):
        with self.assertRaises(ValueError):
            self.build("iphone")
        self.assert_untouched()

    def test_guard_only_targets_apple_screen_time(self):
        for name in ("asus_laptop", "desktop", "habit"):
            dtb.ensure_generic_build_allowed(get_source_definition(name))
        with self.assertRaises(ValueError):
            dtb.ensure_generic_build_allowed(get_source_definition("iphone"))


class TestActivityWatchUnchanged(Base):
    def check_source(self, name: str, device: str):
        self.write_fact(name, (
            fact_row(device, 1, 30, "Utilities", "System Processes")
            + fact_row(device, 2, 90.5, "Utilities", "System Processes")
            + fact_row(device, 3, 120, "Education", "Data & BI Courses")
        ))
        rows, duration, found = self.build(name)
        self.assertTrue(found)
        self.assertEqual(rows, 2)
        self.assertAlmostEqual(duration, 240.5)
        daily = self.read_daily(name)
        self.assertEqual(list(daily[0].keys()), dtb.DAILY_TIME_COLUMNS)
        by_key = {(r["Category"], r["Subcategory"]): r for r in daily}
        self.assertEqual(by_key[("Utilities", "System Processes")]["Event_Count"], "2")
        self.assertAlmostEqual(float(by_key[("Utilities", "System Processes")]["Duration_sec"]), 120.5)
        self.assertEqual(by_key[("Education", "Data & BI Courses")]["Event_Count"], "1")

    def test_laptop_build_unchanged(self):
        self.check_source("asus_laptop", "Laptop")

    def test_desktop_build_unchanged(self):
        self.check_source("desktop", "Desktop")

    def test_laptop_cli_still_passes(self):
        self.write_fact("asus_laptop", fact_row("Laptop", 1, 60, "Utilities", "System Processes"))
        code, output = self.run_main("--source", "asus_laptop", "--date", DAY.isoformat())
        self.assertEqual(code, 0)
        self.assertIn("RESULT: DAILY_TIME BUILD PASSED.", output)

    def test_desktop_cli_still_passes(self):
        self.write_fact("desktop", fact_row("Desktop", 1, 60, "Utilities", "System Processes"))
        code, output = self.run_main("--source", "desktop", "--date", DAY.isoformat())
        self.assertEqual(code, 0)
        self.assertIn("RESULT: DAILY_TIME BUILD PASSED.", output)

    def test_empty_fact_day_still_builds(self):
        self.write_fact("asus_laptop", "")
        rows, duration, found = self.build("asus_laptop")
        self.assertEqual((rows, duration, found), (0, 0.0, True))

    def test_missing_fact_still_reported(self):
        code, output = self.run_main("--source", "desktop", "--date", DAY.isoformat())
        self.assertEqual(code, 1)
        self.assertIn("RESULT: DAILY_TIME BUILD FAILED.", output)


if __name__ == "__main__":
    unittest.main()
