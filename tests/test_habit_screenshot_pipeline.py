"""Unit tests for habit_screenshot_ingest / habit_screenshot_builder (stdlib unittest)."""

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import habit_screenshot_builder as builder  # noqa: E402
import habit_screenshot_ingest as ingest  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONTH = "2026-09"


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def bar_image(path: Path, heights_px, color, baseline=500, x0=20, pitch=20, width=12):
    image = Image.new("RGB", (x0 + pitch * len(heights_px) + 20, baseline + 20), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for i, h in enumerate(heights_px):
        if h > 0:
            left = x0 + i * pitch
            draw.rectangle((left, baseline - h, left + width - 1, baseline - 1), fill=color)
    image.save(path)


def chart_config(category, file, heights_px, color, px_per_min, average, rounding, zero=()):
    return {
        "category": category, "evidence_file": file, "first_date": "2026-09-01",
        "slots": len(heights_px), "region": [0, 0, 20 + 20 * len(heights_px) + 20, 520],
        "color_min": [max(c - 5, 0) for c in color], "color_max": [min(c + 5, 255) for c in color],
        "baseline_y": 500, "px_per_min": px_per_min, "slot_x0": 25.5, "slot_pitch": 20,
        "reference_average_min": average, "rounding_min": rounding,
        "expected_zero_dates": list(zero), "min_bar_width_px": 3, "notes": "test",
        "date_alignment_status": "CONFIRMED",
    }


class Base(unittest.TestCase):
    """A synthetic September evidence folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.month_dir = self.root / "input" / "Habit" / MONTH
        self.month_dir.mkdir(parents=True)
        self.index = []
        self.manifest = []
        self.charts = []
        for name, category, role in (
            ("CAL_STUDY.PNG", "Offline Study Tracker", "MONTHLY_CALENDAR"),
            ("DAY_STUDY_04.PNG", "Offline Study Tracker", "DAILY_DETAIL"),
            ("CAL_JOURNAL.PNG", "Journaling", "MONTHLY_CALENDAR"),
            ("CAL_MEDITATION.PNG", "Meditation", "MONTHLY_CALENDAR"),
            ("CAL_BOOK.PNG", "Read a book", "MONTHLY_CALENDAR"),
            ("DAY_MOTO_11.PNG", "Motorcycle Time", "DAILY_DETAIL"),
            ("CAL_MOTO.PNG", "Motorcycle Time", "MONTHLY_CALENDAR"),
            ("CAL_FAMILY.PNG", "Family Time Tracking", "MONTHLY_CALENDAR"),
        ):
            self.add_image(name, category, role)

    def tearDown(self):
        self.tmp.cleanup()

    def add_image(self, name, category, role, covers="", dup=""):
        Image.new("RGB", (4, 4), (255, 255, 255)).save(self.month_dir / name)
        if not covers:
            covers = "TRUE" if role in ("MONTHLY_CALENDAR", "MONTHLY_BAR") else "FALSE"
        self.index.append({"Evidence_File": name, "Category": category, "Role": role,
                           "Evidence_Date": "", "Covers_Month": covers, "Duplicate_Of": dup, "Notes": ""})

    def add(self, day, category, duration, evidence_type, allocation, file, completed="TRUE"):
        self.manifest.append({"Date": f"2026-09-{day:02d}", "Category": category, "Completed": completed,
                              "Duration_min": duration, "Evidence_Type": evidence_type,
                              "Allocation_Type": allocation, "Evidence_File": file, "Notes": ""})

    def add_bars(self, category, name, heights_px, color, px_per_min, average, rounding, zero=()):
        bar_image(self.month_dir / name, heights_px, color)
        self.index.append({"Evidence_File": name, "Category": category, "Role": "MONTHLY_BAR",
                           "Evidence_Date": "", "Covers_Month": "TRUE", "Duplicate_Of": "", "Notes": ""})
        self.charts.append(chart_config(category, name, heights_px, color, px_per_min, average, rounding, zero))

    def write_inputs(self):
        write_csv(self.month_dir / f"Habit_Screenshot_Index_{MONTH}.csv", ingest.INDEX_COLUMNS, self.index)
        write_csv(self.month_dir / f"Habit_Evidence_Manifest_{MONTH}.csv", ingest.MANIFEST_COLUMNS, self.manifest)
        (self.month_dir / f"Habit_Bar_Charts_{MONTH}.json").write_text(json.dumps(self.charts), encoding="utf-8")

    def normalize(self):
        self.write_inputs()
        return ingest.normalize_month(MONTH, self.month_dir)

    def rows_for(self, result, category):
        return {r.date.day: r for r in result["rows"] if r.category == category}

    def build(self):
        result = self.normalize()
        out = self.root / "normalized"
        path = ingest.write_normalized(result, out)
        days = builder.build_month(MONTH, path, result["calendar_coverage"])
        return result, days, path


# 2–4. Target durations ---------------------------------------------------------------

class TestTargets(Base):
    def test_journaling_meditation_book_targets(self):
        self.add(7, "Journaling", "", "Target Duration", "Target_Derived", "CAL_JOURNAL.PNG")
        self.add(26, "Meditation", "", "Target Duration", "Target_Derived", "CAL_MEDITATION.PNG")
        self.add(3, "Read a book", "", "Target Duration", "Target_Derived", "CAL_BOOK.PNG")
        result = self.normalize()
        self.assertEqual(self.rows_for(result, "Journaling")[7].duration_min, 15)
        self.assertEqual(self.rows_for(result, "Meditation")[26].duration_min, 15)
        self.assertEqual(self.rows_for(result, "Read a book")[3].duration_min, 30)
        for r in result["rows"]:
            self.assertEqual(r.allocation_type, "Target_Derived")
            self.assertEqual(r.evidence_type, "Target Duration")

    def test_target_with_wrong_duration_rejected(self):
        self.add(7, "Journaling", "20", "Target Duration", "Target_Derived", "CAL_JOURNAL.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()

    def test_target_without_configured_target_rejected(self):
        self.add(4, "Offline Study Tracker", "", "Target Duration", "Target_Derived", "CAL_STUDY.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()


# 5–7. Observed values and Motorcycle -----------------------------------------------

class TestObserved(Base):
    def test_offline_study_exact_value(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        row = self.rows_for(self.normalize(), "Offline Study Tracker")[4]
        self.assertEqual((row.duration_min, row.allocation_type, row.evidence_type),
                         (90, "Observed", "Daily Screenshot"))

    def test_motorcycle_exact_and_target_derived(self):
        self.add(11, "Motorcycle Time", "120", "Daily Screenshot", "Observed", "DAY_MOTO_11.PNG")
        self.add(6, "Motorcycle Time", "", "Target Duration", "Target_Derived", "CAL_MOTO.PNG")
        rows = self.rows_for(self.normalize(), "Motorcycle Time")
        self.assertEqual((rows[11].duration_min, rows[11].allocation_type), (120, "Observed"))
        self.assertEqual((rows[6].duration_min, rows[6].allocation_type), (120, "Target_Derived"))

    def test_observed_requires_explicit_duration(self):
        self.add(4, "Offline Study Tracker", "", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()


# 8–10. Inferred bars ------------------------------------------------------------------

class TestBars(Base):
    def test_sleep_relative_bars_calibrated_to_7h55(self):
        heights = [300, 320, 310, 340, 290, 330] * 5
        self.add_bars("Sleep", "SLEEP.PNG", heights, (120, 90, 220), None, 475, 5)
        result = self.normalize()
        rows = self.rows_for(result, "Sleep")
        values = [rows[d].duration_min for d in range(1, 31)]
        self.assertEqual(sum(values), 475 * 30)
        self.assertTrue(all(v % 5 == 0 for v in values))
        self.assertGreater(values[3], values[4])  # taller bar -> longer sleep
        report = result["bar_reports"][0]
        self.assertAlmostEqual(report["calibrated_mean_min"], 475)

    def test_workout_absolute_bars_with_zero_day(self):
        heights = [60, 0, 150, 300, 30] * 6
        heights[18] = 0  # Sep 19
        self.add_bars("Workout", "EX.PNG", heights, (240, 100, 40), 7.5, 28, 1, zero=("2026-09-19",))
        rows = self.rows_for(self.normalize(), "Workout")
        values = [rows[d].duration_min for d in range(1, 31)]
        self.assertEqual(sum(values), 28 * 30)
        self.assertEqual(rows[19].duration_min, 0)
        self.assertEqual(rows[2].duration_min, 0)

    def test_inferred_rows_are_marked_inferred(self):
        self.add_bars("Sleep", "SLEEP.PNG", [300] * 30, (120, 90, 220), None, 475, 5)
        for r in self.normalize()["rows"]:
            self.assertEqual(r.allocation_type, "Inferred")
            self.assertEqual(r.evidence_type, "Monthly Bar Estimate")
            self.assertIn("displayed average 475", r.calibration_reference)

    def test_expected_zero_bar_enforced(self):
        self.add_bars("Workout", "EX.PNG", [60] * 30, (240, 100, 40), 7.5, 28, 1, zero=("2026-09-19",))
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()

    def test_calibration_and_rounding_helpers(self):
        values, stats = ingest.calibrate_bars([10, 20, 30], None, 20, 5)
        self.assertEqual(sum(values), 60)
        self.assertEqual(values, [10, 20, 30])
        self.assertAlmostEqual(stats["calibration_factor"], 1.0)
        self.assertEqual(ingest.allocate_rounded([2.4, 2.4, 2.2], 1, 7), [3, 2, 2])


# 11. Targets are never Observed ----------------------------------------------------------

class TestTargetNeverObserved(Base):
    def test_target_duration_cannot_be_labelled_observed(self):
        self.add(7, "Journaling", "15", "Target Duration", "Observed", "CAL_JOURNAL.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()

    def test_built_target_rows_keep_target_label(self):
        self.add(7, "Journaling", "", "Target Duration", "Target_Derived", "CAL_JOURNAL.PNG")
        _, days, _ = self.build()
        row = next(r for r in days["2026-09-07"] if r["Category"] == "Journaling")
        self.assertEqual(row["Allocation_Type"], "Target_Derived")
        self.assertEqual(row["Duration_sec"], 900)


# 12. Completed-only --------------------------------------------------------------------

class TestCompletedOnly(Base):
    def test_completed_without_duration_is_review_zero(self):
        self.add(4, "Offline Study Tracker", "", "Completed Without Duration", "Review", "CAL_STUDY.PNG")
        _, days, _ = self.build()
        row = next(r for r in days["2026-09-04"] if r["Category"] == "Offline Study Tracker")
        self.assertEqual((row["Duration_sec"], row["Allocation_Type"], row["Event_Count"]), (0, "Review", 1))
        self.assertEqual(row["Evidence_Type"], "Completed Without Duration")

    def test_completed_only_must_not_carry_duration(self):
        self.add(4, "Offline Study Tracker", "30", "Completed Without Duration", "Review", "CAL_STUDY.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()


# 13. Provenance ---------------------------------------------------------------------------

class TestProvenance(Base):
    def test_evidence_source_traces_file(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        _, days, _ = self.build()
        row = next(r for r in days["2026-09-04"] if r["Category"] == "Offline Study Tracker")
        self.assertEqual(row["Evidence_Source"], "input/Habit/2026-09/DAY_STUDY_04.PNG")
        empty = next(r for r in days["2026-09-05"] if r["Category"] == "Offline Study Tracker")
        self.assertEqual((empty["Duration_sec"], empty["Allocation_Type"]), (0, "Observed"))
        self.assertIn("CAL_STUDY.PNG", empty["Evidence_Source"])
        self.assertIn("not completed", empty["Evidence_Source"])

    def test_untracked_category_is_review_no_evidence(self):
        _, days, _ = self.build()
        row = next(r for r in days["2026-09-01"] if r["Category"] == "Sleep")
        self.assertEqual((row["Allocation_Type"], row["Evidence_Type"]), ("Review", "No Evidence"))

    def test_every_day_has_every_category(self):
        _, days, _ = self.build()
        self.assertEqual(len(days), 30)
        for rows in days.values():
            self.assertEqual([r["Category"] for r in rows], list(ingest.HABIT_CATEGORIES))
            self.assertEqual(list(rows[0].keys()), builder.DAILY_COLUMNS)

    def test_unindexed_or_foreign_evidence_rejected(self):
        Image.new("RGB", (4, 4)).save(self.month_dir / "NEW.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()
        (self.month_dir / "NEW.PNG").unlink()
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_MOTO_11.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()


# 14. Duplicate evidence ---------------------------------------------------------------------

class TestDuplicates(Base):
    def test_duplicate_screenshot_does_not_double_count(self):
        self.add_image("CAL_FAMILY_COPY.PNG", "Family Time Tracking", "DUPLICATE", dup="CAL_FAMILY.PNG")
        self.add(13, "Family Time Tracking", "540", "Monthly Calendar", "Observed", "CAL_FAMILY.PNG")
        self.add(13, "Family Time Tracking", "540", "Monthly Calendar", "Observed", "CAL_FAMILY_COPY.PNG")
        _, days, _ = self.build()
        rows = [r for r in days["2026-09-13"] if r["Category"] == "Family Time Tracking"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Duration_sec"], 540 * 60)

    def test_identical_rows_from_two_files_merge_with_supporting_file(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        self.manifest.append(dict(self.manifest[-1], Evidence_File="CAL_STUDY.PNG"))
        row = self.rows_for(self.normalize(), "Offline Study Tracker")[4]
        self.assertEqual(row.duration_min, 90)
        self.assertEqual(row.supporting_files, ["CAL_STUDY.PNG"])

    def test_conflicting_duplicates_rejected(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        self.add(4, "Offline Study Tracker", "60", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()


# 15. No cumulative state ------------------------------------------------------------------------

class TestNoCumulativeState(Base):
    def test_builds_without_baselines_or_previous_snapshots(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        self.assertFalse((self.root / "input" / "Integrated").exists())
        self.assertFalse((self.root / "input" / "Habit" / "2026-08").exists())
        _, days, path = self.build()
        receipts = builder.write_month(MONTH, days, self.root / "out", path, force=False)
        self.assertEqual(len(receipts), 30)
        for name in ("Habit_Initial_Baselines", "Previous_Value", "Delta_Status", "Tracking_Mode"):
            self.assertNotIn(name, (self.root / "out" / "Daily" / "Time" / "Habit" / "OffDevice"
                                    / "Daily_Time_2026-09-04.csv").read_text(encoding="utf-8"))

    def test_existing_output_not_overwritten_without_force(self):
        self.add(4, "Offline Study Tracker", "90", "Daily Screenshot", "Observed", "DAY_STUDY_04.PNG")
        _, days, path = self.build()
        builder.write_month(MONTH, days, self.root / "out", path, force=False)
        builder.write_month(MONTH, days, self.root / "out", path, force=False)  # identical: fine
        days["2026-09-04"][3]["Duration_sec"] = 1
        with self.assertRaises(builder.BuildError):
            builder.write_month(MONTH, days, self.root / "out", path, force=False)


# Bar-chart date mapping ---------------------------------------------------------------------------

class TestBarDateMapping(Base):
    def test_alignment_status_required(self):
        self.add_bars("Sleep", "SLEEP.PNG", [300] * 30, (120, 90, 220), None, 475, 5)
        del self.charts[0]["date_alignment_status"]
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()

    def test_review_mapping_flags_rows_and_shifted_bars_leave_month(self):
        heights = [300 + i for i in range(30)]
        self.add_bars("Sleep", "SLEEP.PNG", heights, (120, 90, 220), None, 475, 5)
        self.charts[0].update(first_date="2026-09-02", date_alignment_status="REVIEW")
        result = self.normalize()
        rows = self.rows_for(result, "Sleep")
        self.assertNotIn(1, rows)                       # no bar maps to Sep 1
        self.assertEqual(len(rows), 29)                 # bar 30 -> Oct 1 excluded
        self.assertTrue(all(r.date_mapping_status == "REVIEW" for r in rows.values()))
        self.assertTrue(all(r.allocation_type == "Inferred" for r in rows.values()))
        report = result["bar_reports"][0]
        self.assertEqual(report["bars_outside_month"][0]["date"], "2026-10-01")
        self.assertEqual(report["category_dates_without_value"], ["2026-09-01"])
        self.assertAlmostEqual(report["calibrated_mean_min"], 475)  # calibrated over all 30 bars

    def test_bar_chart_is_not_calendar_coverage(self):
        self.add_bars("Sleep", "SLEEP.PNG", [300] * 30, (120, 90, 220), None, 475, 5)
        self.charts[0].update(first_date="2026-09-02", date_alignment_status="REVIEW")
        _, days, _ = self.build()
        sep1 = next(r for r in days["2026-09-01"] if r["Category"] == "Sleep")
        self.assertEqual((sep1["Allocation_Type"], sep1["Evidence_Type"]), ("Review", "No Evidence"))
        sep2 = next(r for r in days["2026-09-02"] if r["Category"] == "Sleep")
        self.assertEqual(sep2["Allocation_Type"], "Inferred")
        self.assertIn(builder.DATE_MAPPING_REVIEW, sep2["Evidence_Type"])
        self.assertEqual(len(builder.unresolved_date_mappings(days)), 29)

    def test_confirmed_mapping_not_flagged(self):
        self.add_bars("Sleep", "SLEEP.PNG", [300] * 30, (120, 90, 220), None, 475, 5)
        _, days, _ = self.build()
        self.assertEqual(builder.unresolved_date_mappings(days), [])

    def test_canonical_write_refused_while_mapping_unresolved(self):
        self.add_bars("Sleep", "SLEEP.PNG", [300] * 30, (120, 90, 220), None, 475, 5)
        self.charts[0]["date_alignment_status"] = "REVIEW"
        result = self.normalize()
        out = self.root / "normalized"
        ingest.write_normalized(result, out)
        canonical = self.root / "canonical_output"
        original = builder.OUTPUT_ROOT
        builder.OUTPUT_ROOT = canonical
        try:
            code = builder.main(["--month", MONTH, "--normalized-dir", str(out),
                                 "--output-root", str(canonical)])
            self.assertEqual(code, 1)
            self.assertFalse((canonical / "Daily").exists())
            staged = self.root / "staging"
            self.assertEqual(builder.main(["--month", MONTH, "--normalized-dir", str(out),
                                           "--output-root", str(staged)]), 0)
            self.assertTrue((staged / "Daily" / "Time" / "Habit" / "OffDevice").exists())
        finally:
            builder.OUTPUT_ROOT = original


# Weekly charts: emit selected dates and cross-check the monthly mapping -------------------------

class TestWeeklyCrossCheck(Base):
    MONTHLY = [300 + (i * 37) % 90 for i in range(30)]  # distinctive pattern

    def setup_month_and_week(self, monthly_first, week_heights, week_first="2026-09-11", emit=None):
        self.add_bars("Sleep", "MONTH.PNG", self.MONTHLY, (120, 90, 220), None, 475, 1)
        self.charts[0].update(first_date=monthly_first)
        bar_image(self.month_dir / "WEEK.PNG", week_heights, (120, 90, 220))
        self.index.append({"Evidence_File": "WEEK.PNG", "Category": "Sleep", "Role": "WEEKLY_BAR",
                           "Evidence_Date": "", "Covers_Month": "FALSE", "Duplicate_Of": "", "Notes": ""})
        week = chart_config("Sleep", "WEEK.PNG", week_heights, (120, 90, 220), None, 0, 1)
        week.update(first_date=week_first, cross_check_against="MONTH.PNG", cross_check_tolerance_min=10,
                    emit_dates=emit if emit is not None else [])
        self.charts.append(week)

    def week_from_month(self, monthly_first, week_first="2026-09-11"):
        from datetime import date as d
        offset = (d.fromisoformat(week_first) - d.fromisoformat(monthly_first)).days
        heights = self.MONTHLY[offset:offset + 7]
        return heights

    def calibrate_week(self, heights, monthly_first, week_first="2026-09-11"):
        # Reference average consistent with the monthly calibration for those dates.
        month_vals, _ = ingest.calibrate_bars(self.MONTHLY, None, 475, 1)
        from datetime import date as d
        offset = (d.fromisoformat(week_first) - d.fromisoformat(monthly_first)).days
        return round(sum(month_vals[offset:offset + 7]) / 7)

    def test_matching_week_confirms_mapping(self):
        heights = self.week_from_month("2026-09-02")
        self.setup_month_and_week("2026-09-02", heights)
        self.charts[1]["reference_average_min"] = self.calibrate_week(heights, "2026-09-02")
        result = self.normalize()
        report = next(r for r in result["bar_reports"] if r["evidence_file"] == "WEEK.PNG")
        self.assertLessEqual(report["cross_check"]["max_abs_diff_min"], 10)
        self.assertEqual(len(report["cross_check"]["dates"]), 7)
        self.assertEqual(report["emitted_dates"], [])

    def test_shifted_mapping_is_rejected(self):
        heights = self.week_from_month("2026-09-02")
        self.setup_month_and_week("2026-09-01", heights)  # wrong: monthly assumed to start Sep 1
        self.charts[1]["reference_average_min"] = self.calibrate_week(heights, "2026-09-02")
        with self.assertRaises(ingest.EvidenceError):
            self.normalize()

    def test_weekly_chart_supplies_uncovered_date(self):
        heights = [400, 410, 420, 430, 300, 310, 320]  # Aug 29 .. Sep 4
        self.add_bars("Sleep", "MONTH.PNG", self.MONTHLY, (120, 90, 220), None, 475, 1)
        self.charts[0].update(first_date="2026-09-02")
        bar_image(self.month_dir / "WEEK.PNG", heights, (120, 90, 220))
        self.index.append({"Evidence_File": "WEEK.PNG", "Category": "Sleep", "Role": "WEEKLY_BAR",
                           "Evidence_Date": "", "Covers_Month": "FALSE", "Duplicate_Of": "", "Notes": ""})
        week = chart_config("Sleep", "WEEK.PNG", heights, (120, 90, 220), None, 420, 1)
        week.update(first_date="2026-08-29", emit_dates=["2026-09-01"])
        self.charts.append(week)
        result = self.normalize()
        rows = self.rows_for(result, "Sleep")
        self.assertEqual(len(rows), 30)                         # Sep 1 (weekly) + Sep 2..30 (monthly)
        self.assertEqual(rows[1].evidence_type, "Weekly Bar Estimate")
        self.assertEqual(rows[1].evidence_file, "WEEK.PNG")
        self.assertEqual(rows[2].evidence_file, "MONTH.PNG")
        monthly = next(r for r in result["bar_reports"] if r["evidence_file"] == "MONTH.PNG")
        self.assertEqual([b["date"] for b in monthly["bars_outside_month"]], ["2026-10-01"])
        self.assertEqual(monthly["category_dates_without_value"], [])

    def test_weekly_role_is_not_calendar_coverage(self):
        self.test_weekly_chart_supplies_uncovered_date()
        self.assertNotIn("Sleep", self.normalize()["calendar_coverage"])


# 17. habit_manual_adjustments.py untouched -----------------------------------------------------

class TestManualAdjustmentsUntouched(unittest.TestCase):
    EXPECTED_SHA256 = "7c5ddb337a7c2bdd43fda2f98f09734d9702671ab0cf201b7e0d1f69813f1016"  # on-disk bytes (CRLF checkout of git blob d44de6d)

    def test_byte_identical(self):
        actual = hashlib.sha256((PROJECT_ROOT / "habit_manual_adjustments.py").read_bytes()).hexdigest()
        self.assertEqual(actual, self.EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main()
