"""Unit tests for opal_screen_time_reconstruction (stdlib unittest)."""

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import opal_screen_time_reconstruction as rec  # noqa: E402

CATS = rec.APPLE_SCREEN_TIME_CATEGORIES
REPORT_COLUMNS = list(rec.REQUIRED_REPORT_COLUMNS)
REFERENCE_COLUMNS = list(rec.REQUIRED_REFERENCE_COLUMNS)
DAILY_HEADER = (
    "Date,Source,Category,Subcategory,Duration_sec,Event_Count,"
    "Allocation_Type,Evidence_Type,Evidence_Source\n"
)
# Observed category mix used for every synthetic Apple day (fractions of the
# visible total) plus a fixed derived residual.
MIX = {"Social Networking": 0.6, "Productivity & Finance": 0.25,
       "Shopping & Food": 0.1, "Other": 0.05}
RESIDUAL_SEC = 600


def label(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def write_apple_daily(directory: Path, day: date, minutes: float, mix=None) -> Path:
    """Daily_Time with visible categories + a derived residual summing to minutes."""
    mix = mix or MIX
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"Daily_Time_{day.isoformat()}.csv"
    total = int(round(minutes * 60))
    visible = total - RESIDUAL_SEC
    lines = [DAILY_HEADER]
    used = 0
    items = list(mix.items())
    for i, (cat, frac) in enumerate(items):
        sec = visible - used if i == len(items) - 1 else int(visible * frac)
        used += sec
        lines.append(f"{day},iphone,{cat},{cat},{sec},1,Observed,Apple Screen Time Category,CATEGORIES\n")
    lines.append(f"{day},iphone,Utilities,Screen Time / System,{RESIDUAL_SEC},1,Derived,"
                 "Apple Headline Screen Time Residual,TOTAL vs CATEGORIES\n")
    path.write_text("".join(lines), encoding="utf-8")
    meta = directory / f"Daily_Time_{day.isoformat()}.metadata.json"
    meta.write_text(json.dumps({"reconciliation": {"headline_seconds": total}}), encoding="utf-8")
    return path


def report_row(report_id, week_start, minutes, *, basis="HEADER_LABEL", status="CONFIRMED",
               transcription="VERIFIED", header=None, capture="2026-10-02 09:00:00",
               header_avg=None, folder="2026-08/Opal", files=("S.PNG", "B.PNG")):
    ws = date.fromisoformat(week_start) if week_start else None
    if header is None:
        header = (
            f"{ws.day} {ws.strftime('%b %Y')} – {(ws + timedelta(5)).day} "
            f"{(ws + timedelta(5)).strftime('%b %Y')}" if ws else "Last Week"
        )
    avg = header_avg if header_avg is not None else round(sum(minutes) / 7)
    row = {
        "Report_ID": report_id, "Screenshot_Folder": folder,
        "Summary_Screenshot": files[0], "Bars_Screenshot": files[1],
        "Capture_Datetime": capture, "Header_Label": header,
        "Header_Average": label(avg), "Week_Start": week_start or "",
        "Date_Mapping_Basis": basis, "Date_Mapping_Status": status,
        "Transcription_Method": "test", "Transcription_Status": transcription, "Notes": "",
    }
    for wd, m in zip(rec.WEEKDAYS, minutes):
        row[wd] = label(m)
    return row


def write_csv_rows(path: Path, columns, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_reports(path: Path, rows) -> Path:
    return write_csv_rows(path, REPORT_COLUMNS, rows)


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


AUG_WEEKS = {
    "2026-08-03": [195, 165, 145, 105, 90, 120, 105],
    "2026-08-10": [195, 200, 105, 150, 165, 105, 105],
}
SEP_WEEKS = {
    # Mirrors the late-added report: Mon 2026-08-31 .. Sun 2026-09-06.
    "2026-08-31": [150, 75, 135, 130, 150, 75, 90],
    "2026-09-07": [150, 120, 135, 135, 165, 90, 120],
}


class Fixture(unittest.TestCase):
    """Temporary project: two calibration weeks, two September reports."""

    apple_offset = [30, 25, 28, 32, 35, 27, 29]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.apple_dir = self.root / "output" / "Daily" / "Time" / "AppleScreenTime" / "iPhone"
        self.shots = self.root / "input" / "iPhone" / "ScreenTime"
        self.apple_values = {}
        rows = []
        for ws, mins in AUG_WEEKS.items():
            start = date.fromisoformat(ws)
            for i, m in enumerate(mins):
                apple = m + self.apple_offset[i]
                self.apple_values[start + timedelta(i)] = apple
                write_apple_daily(self.apple_dir, start + timedelta(i), apple)
            rows.append(report_row(f"R-{ws}", ws, mins, files=(f"S{ws}.PNG", f"B{ws}.PNG")))
        for ws, mins in SEP_WEEKS.items():
            rows.append(report_row(f"R-{ws}", ws, mins, folder="2026-09/Opal",
                                   files=(f"S{ws}.PNG", f"B{ws}.PNG")))
        self.rows = rows
        self.reports_csv = write_reports(self.root / "input" / "iPhone" / "Opal" / "r.csv", rows)
        for row in rows:
            for key in ("Summary_Screenshot", "Bars_Screenshot"):
                p = self.shots / row["Screenshot_Folder"] / row[key]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"png" + row[key].encode())
        self.reference_csv = write_csv_rows(
            self.root / "input" / "iPhone" / "Reconstruction" / "ref.csv", REFERENCE_COLUMNS,
            [
                {"Date": "2026-09-23", "Headline_sec": 9000, "Category": c, "Duration_sec": s,
                 "Source_Screenshots": "x", "Use_As_Reference": "TRUE",
                 "Transcription_Status": "T", "Notes": ""}
                for c, s in (("Social Networking", 3000), ("Productivity & Finance", 1200),
                             ("Shopping & Food", 500), ("Other", 300))
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_rec(self, out_name="out", missing=("2026-09-01", "2026-09-13"), **kw):
        return rec.run(
            opal_reports_path=self.reports_csv,
            screenshot_root=self.shots,
            apple_daily_dir=self.apple_dir,
            output_dir=self.root / "output" / "Analysis" / "Reconstruction" / out_name,
            missing_start=date.fromisoformat(missing[0]),
            missing_end=date.fromisoformat(missing[1]),
            calibration_start=date(2026, 8, 3),
            calibration_end=date(2026, 8, 16),
            history_start=date(2026, 8, 1),
            history_end=date(2026, 8, 31),
            september_reference_path=self.reference_csv,
            reference_start=date(2026, 9, 23),
            reference_end=date(2026, 9, 30),
            **kw,
        )

    def read_out(self, name, out_name="out"):
        path = self.root / "output" / "Analysis" / "Reconstruction" / out_name / name
        with path.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))


# 1. Opal weekly date mapping -------------------------------------------------------

class TestWeeklyMapping(Fixture):
    def test_monday_to_sunday_order(self):
        days = rec.expand_reports(rec.load_opal_reports(self.reports_csv))
        week = [d for d in days if d.report_id == "R-2026-09-07"]
        self.assertEqual([d.date for d in week],
                         [date(2026, 9, 7) + timedelta(i) for i in range(7)])
        self.assertEqual([d.date.weekday() for d in week], list(range(7)))
        self.assertEqual([d.opal_minutes for d in week], SEP_WEEKS["2026-09-07"])

    def test_header_mismatch_is_not_mapped(self):
        row = report_row("X", "2026-09-07", [60] * 7, header="14 Sep 2026 – 19 Sep 2026")
        report = rec.load_opal_reports(write_reports(self.root / "bad.csv", [row]))[0]
        self.assertEqual(report.mapping_status, "UNKNOWN")
        self.assertTrue(all(d.date is None for d in rec.expand_reports([report])))

    def test_non_monday_week_start_rejected(self):
        row = report_row("X", "2026-09-08", [60] * 7, header="8 Sep 2026 – 13 Sep 2026")
        report = rec.load_opal_reports(write_reports(self.root / "bad.csv", [row]))[0]
        self.assertEqual(report.mapping_status, "UNKNOWN")

    def test_last_week_mapping_relative_to_capture(self):
        row = report_row("LW", "2026-09-21", [60] * 7, basis="LAST_WEEK_RELATIVE_TO_CAPTURE",
                         status="CONFIRMED", header="Last Week", capture="2026-10-02 09:47:38")
        report = rec.load_opal_reports(write_reports(self.root / "lw.csv", [row]))[0]
        self.assertEqual(report.week_start, date(2026, 9, 21))
        self.assertEqual(report.mapping_status, "CONFIRMED")
        wrong = report_row("LW", "2026-09-14", [60] * 7, basis="LAST_WEEK_RELATIVE_TO_CAPTURE",
                           status="CONFIRMED", header="Last Week", capture="2026-10-02 09:47:38")
        report = rec.load_opal_reports(write_reports(self.root / "lw2.csv", [wrong]))[0]
        self.assertEqual(report.mapping_status, "UNKNOWN")

    def test_header_average_check(self):
        ok = report_row("A", "2026-09-07", [120] * 7, header_avg=121)
        bad = report_row("B", "2026-09-14", [120] * 7, header_avg=140,
                         header="14 Sep 2026 – 19 Sep 2026")
        reports = rec.load_opal_reports(write_reports(self.root / "h.csv", [ok, bad]))
        self.assertTrue(reports[0].header_check_passed)
        self.assertFalse(reports[1].header_check_passed)

    def test_duplicate_dates_rejected(self):
        a = report_row("A", "2026-09-07", [60] * 7)
        b = report_row("B", "2026-09-07", [70] * 7)
        with self.assertRaises(rec.ReconstructionError):
            rec.expand_reports(rec.load_opal_reports(write_reports(self.root / "d.csv", [a, b])))

    def test_duration_labels(self):
        self.assertEqual(rec.parse_duration_label("2h 15m"), 135)
        self.assertEqual(rec.parse_duration_label("2h 10m"), 130)
        self.assertEqual(rec.parse_duration_label("2h"), 120)
        self.assertEqual(rec.parse_duration_label("45m"), 45)
        with self.assertRaises(rec.ReconstructionError):
            rec.parse_duration_label("")


# 2. Newly added Sep 1–6 report ------------------------------------------------------

class TestSeptemberFirstWeek(Fixture):
    def test_week_spanning_month_boundary_maps_and_estimates(self):
        days = {d.date: d for d in rec.expand_reports(rec.load_opal_reports(self.reports_csv))}
        self.assertEqual(days[date(2026, 8, 31)].weekday, "Mon")
        self.assertEqual(days[date(2026, 9, 6)].opal_minutes, 90)
        summary = self.run_rec()
        for d in ("2026-09-01", "2026-09-06"):
            self.assertIn(d, summary["estimated_dates"])
        self.assertEqual(summary["no_opal_dates"], [])

    def test_untranscribed_screenshot_is_reported(self):
        extra = self.shots / "2026-09" / "Opal" / "IMG_9999.PNG"
        extra.write_bytes(b"new")
        summary = self.run_rec()
        self.assertEqual(summary["opal_screenshots_untranscribed"], ["2026-09/Opal/IMG_9999.PNG"])


# 3–4. Calibration arithmetic and reproducibility ------------------------------------

class TestCalibrationArithmetic(Fixture):
    def pairs(self):
        reports = rec.load_opal_reports(self.reports_csv)
        return rec.build_calibration_pairs(
            rec.expand_reports(reports), self.apple_dir, date(2026, 8, 3), date(2026, 8, 16))

    def test_totals_ratio_and_differences(self):
        pairs = self.pairs()
        self.assertEqual(len(pairs), 14)
        cal = rec.summarize_calibration(pairs)
        opal_total = sum(sum(v) for v in AUG_WEEKS.values())
        apple_total = sum(self.apple_values.values())
        self.assertAlmostEqual(cal["total_opal_minutes"], opal_total)
        self.assertAlmostEqual(cal["total_apple_minutes"], apple_total)
        self.assertAlmostEqual(cal["overall_opal_over_apple"], opal_total / apple_total)
        self.assertAlmostEqual(cal["mean_daily_difference_min"], sum(self.apple_offset) / 7)
        self.assertAlmostEqual(cal["median_daily_difference_min"], 29)
        self.assertEqual([w["apple_minus_opal_minutes"] for w in cal["weekly"]],
                         [sum(self.apple_offset)] * 2)

    def test_calibration_excludes_dates_outside_window(self):
        # 2026-08-31 has Opal and could have Apple, but is outside the window.
        write_apple_daily(self.apple_dir, date(2026, 8, 31), 500)
        self.assertNotIn(date(2026, 8, 31), {p.date for p in self.pairs()})

    def test_calibration_requires_a_full_week(self):
        reports = rec.load_opal_reports(self.reports_csv)
        pairs = rec.build_calibration_pairs(
            rec.expand_reports(reports), self.apple_dir, date(2026, 8, 3), date(2026, 8, 5))
        with self.assertRaises(rec.ReconstructionError):
            rec.summarize_calibration(pairs)

    def test_calibration_reproducible(self):
        first = rec.summarize_calibration(self.pairs())
        second = rec.summarize_calibration(self.pairs())
        self.assertEqual(first, second)
        summary = self.run_rec()
        self.assertAlmostEqual(summary["calibration_minutes"], first["mean_daily_difference_min"])


# 5. Missing Opal -> REVIEW ------------------------------------------------------------

class TestMissingOpal(Fixture):
    def test_missing_opal_is_review_with_no_value(self):
        self.run_rec(missing=("2026-09-01", "2026-09-15"))
        rows = {r["Date"]: r for r in self.read_out("04_Reconstructed_Daily_Totals.csv")}
        for d in ("2026-09-14", "2026-09-15"):
            self.assertEqual(rows[d]["Estimate_Status"], "NO_OPAL_EVIDENCE")
            self.assertEqual(rows[d]["Review_Status"], "REVIEW")
            self.assertEqual(rows[d]["Estimated_Apple_Minutes"], "")
        alloc_dates = {r["Date"] for r in self.read_out("05_Reconstructed_Category_Allocation.csv")}
        self.assertNotIn("2026-09-14", alloc_dates)
        coverage = {r["Date"]: r for r in self.read_out("10_Coverage_Report.csv")}
        self.assertEqual(coverage["2026-09-14"]["Opal_Available"], "False")


# 6. Daily Apple-equivalent calculation -------------------------------------------------

class TestEstimatedTotal(Fixture):
    def test_estimate_rule(self):
        self.assertEqual(rec.estimate_apple_minutes(120, 28.5), 149)
        self.assertEqual(rec.estimate_apple_minutes(120, 28.4999), 148)
        self.assertEqual(rec.estimate_apple_minutes(0, -10), 0)

    def test_estimates_use_calibrated_constant(self):
        summary = self.run_rec()
        mean_diff = sum(self.apple_offset) / 7
        rows = {r["Date"]: r for r in self.read_out("04_Reconstructed_Daily_Totals.csv")}
        for i, m in enumerate(SEP_WEEKS["2026-09-07"]):
            d = (date(2026, 9, 7) + timedelta(i)).isoformat()
            self.assertEqual(int(rows[d]["Estimated_Apple_Minutes"]), rec.round_half_up(m + mean_diff))
            self.assertEqual(rows[d]["Review_Status"], "READY")
        self.assertEqual(summary["calibration_status"], "FINAL")

    def test_pending_transcription_makes_estimates_review(self):
        for row in self.rows:
            row["Transcription_Status"] = "PENDING_HUMAN_REVIEW"
        write_reports(self.reports_csv, self.rows)
        summary = self.run_rec()
        self.assertEqual(summary["calibration_status"], "PROVISIONAL_PENDING_TRANSCRIPTION_REVIEW")
        rows = self.read_out("04_Reconstructed_Daily_Totals.csv")
        self.assertTrue(all(r["Review_Status"] == "REVIEW" for r in rows))

    def test_model_predictions(self):
        self.assertEqual(rec.predict("B_additive", {"mean_difference": 30}, 100), 130)
        self.assertAlmostEqual(rec.predict("A_multiplicative", {"ratio": 0.8}, 100), 125)
        self.assertAlmostEqual(rec.predict("C_regression", {"intercept": 10, "slope": 1.1}, 100), 120)


# 7. Historical category proportions ------------------------------------------------------

class TestHistoricalProportions(Fixture):
    def test_pooled_shares_are_time_weighted(self):
        shares = rec.pooled_shares([
            {"Social Networking": 600, "Utilities": 0},
            {"Social Networking": 0, "Utilities": 1800},
        ])
        self.assertAlmostEqual(shares["Social Networking"], 0.25)
        self.assertAlmostEqual(shares["Utilities"], 0.75)
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        self.assertEqual(shares["Games"], 0)

    def test_history_keeps_residual_in_utilities_and_tracks_visible(self):
        day = rec.load_apple_category_day(self.apple_dir, date(2026, 8, 3))
        self.assertEqual(day.totals["Utilities"], RESIDUAL_SEC)
        self.assertEqual(day.visible["Utilities"], 0)
        self.assertEqual(day.total - day.visible_total, RESIDUAL_SEC)

    def test_unknown_category_rejected(self):
        write_apple_daily(self.apple_dir, date(2026, 8, 20), 100, mix={"News": 1.0})
        with self.assertRaises(rec.ReconstructionError):
            rec.load_apple_category_day(self.apple_dir, date(2026, 8, 20))

    def test_allocation_uses_history_not_equal(self):
        self.run_rec()
        rows = [r for r in self.read_out("05_Reconstructed_Category_Allocation.csv")
                if r["Date"] == "2026-09-07"]
        by_cat = {r["Category"]: int(r["Duration_sec"]) for r in rows}
        self.assertEqual(by_cat["Games"], 0)
        self.assertGreater(by_cat["Social Networking"], by_cat["Productivity & Finance"])
        self.assertGreater(by_cat["Utilities"], 0)  # residual share
        self.assertEqual(len(set(by_cat.values())) > 1, True)


# 8. Weekday proportions ---------------------------------------------------------------------

class TestWeekdayProportions(Fixture):
    def test_weekday_support_and_selection(self):
        history = rec.load_category_history(self.apple_dir, date(2026, 8, 1), date(2026, 8, 31))
        support = rec.weekday_support(history)
        self.assertEqual(support, {i: 2 for i in range(7)})
        _, summary = rec.validate_category_models(history)
        model, reason = rec.select_category_model(history, summary)
        self.assertEqual(model, rec.MODEL_OVERALL)
        self.assertIn("not supported", reason)

    def test_weekday_shares_use_only_that_weekday(self):
        history = rec.load_category_history(self.apple_dir, date(2026, 8, 1), date(2026, 8, 31))
        monday = rec.shares_for(rec.MODEL_WEEKDAY, history, 0)
        expected = rec.pooled_shares([d.totals for d in history if d.date.weekday() == 0])
        self.assertEqual(monday, expected)

    def test_weekday_distribution_output(self):
        self.run_rec()
        rows = self.read_out("07_Weekday_Category_Distribution.csv")
        self.assertEqual(len(rows), 7 * len(CATS))
        self.assertTrue(all(r["Supported"] == "False" for r in rows))


# 9. Category model reconciliation / validation ------------------------------------------------

class TestCategoryValidation(Fixture):
    def test_validation_reconciles_and_history_beats_equal(self):
        history = rec.load_category_history(self.apple_dir, date(2026, 8, 1), date(2026, 8, 31))
        per_cat, summary = rec.validate_category_models(history)
        by_model = {s["Model"]: s for s in summary}
        for s in summary:
            self.assertEqual(s["Max_Total_Reconciliation_Error_Sec"], 0)
        self.assertLess(by_model[rec.MODEL_OVERALL]["Mean_Daily_Misallocated_Min"],
                        by_model[rec.MODEL_EQUAL]["Mean_Daily_Misallocated_Min"])
        self.assertEqual(len(per_cat), 3 * len(CATS))

    def test_leave_one_out_excludes_the_day(self):
        history = rec.load_category_history(self.apple_dir, date(2026, 8, 1), date(2026, 8, 31))
        target = history[0].date
        with_day = rec.shares_for(rec.MODEL_OVERALL, history, None)
        without = rec.shares_for(rec.MODEL_OVERALL, history, None, exclude=target)
        expected = rec.pooled_shares([d.totals for d in history if d.date != target])
        self.assertEqual(without, expected)
        self.assertNotEqual(with_day, without)

    def test_september_comparison(self):
        history = rec.load_category_history(self.apple_dir, date(2026, 8, 1), date(2026, 8, 31))
        reference = rec.load_september_reference(
            self.reference_csv, self.apple_dir, date(2026, 9, 23), date(2026, 9, 30))
        result = rec.compare_september(history, reference)
        self.assertEqual(result["days"], 1)
        self.assertTrue(result["consistent"])
        self.assertAlmostEqual(sum(r["September_Observed_Share_Pct"] for r in result["rows"]), 100)


# 10. Category values sum exactly to the estimated total -----------------------------------------

class TestExactAllocation(Fixture):
    def test_largest_remainder_sums_exactly(self):
        shares = {"Social Networking": 0.62, "Utilities": 0.155, "Productivity & Finance": 0.14,
                  "Shopping & Food": 0.037, "Games": 0.0002, "Other": 0.0478}
        for total in (0, 1, 7, 59, 8940, 8941, 14399, 86401):
            parts = rec.allocate_by_shares(total, shares)
            self.assertEqual(sum(parts.values()), total)
            self.assertEqual(list(parts), list(CATS))

    def test_equal_shares_still_exact(self):
        parts = rec.allocate_by_shares(149 * 60, rec.equal_shares())
        self.assertEqual(set(parts.values()), {745})

    def test_output_rows_reconcile(self):
        self.run_rec()
        rows = self.read_out("05_Reconstructed_Category_Allocation.csv")
        totals = {r["Date"]: int(r["Estimated_Apple_Seconds"])
                  for r in self.read_out("04_Reconstructed_Daily_Totals.csv")
                  if r["Estimate_Status"] == "ESTIMATED"}
        per_day = {}
        for r in rows:
            per_day[r["Date"]] = per_day.get(r["Date"], 0) + int(r["Duration_sec"])
        self.assertEqual(per_day, totals)


# 11. Provenance -------------------------------------------------------------------------------

class TestProvenance(Fixture):
    def test_rows_marked_as_estimated(self):
        self.run_rec()
        rows = self.read_out("05_Reconstructed_Category_Allocation.csv")
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["Allocation_Type"], "Estimated")
            self.assertEqual(r["Evidence_Type"], "Opal_Calibrated_Estimate")
            self.assertEqual(r["Evidence_Source"], "Opal + August Apple Screen Time calibration")
            self.assertEqual(r["Source_Detail"], "AppleScreenTime_Estimated")
            self.assertEqual(r["Category_Allocation"], "Historical Apple category distribution")
            self.assertEqual(r["Category_Model"], rec.MODEL_OVERALL)
            self.assertIn("August 2026 observed Apple Screen Time", r["Category_History"])
            self.assertIn("Observed September Apple Screen Time", r["Current_Period_Validation"])
            self.assertEqual(r["Event_Count"], "0")
            self.assertEqual(r["Subcategory"], r["Category"])
        out = self.root / "output" / "Analysis" / "Reconstruction" / "out"
        self.assertIn("ESTIMATED", (out / "13_Provenance_Report.md").read_text(encoding="utf-8"))


# 12. Observed Apple data never overwritten ---------------------------------------------------------

class TestObservedNeverOverwritten(Fixture):
    def test_observed_date_in_missing_window_is_skipped(self):
        observed = write_apple_daily(self.apple_dir, date(2026, 9, 9), 200)
        before = observed.read_bytes()
        self.run_rec()
        self.assertEqual(observed.read_bytes(), before)
        rows = {r["Date"]: r for r in self.read_out("04_Reconstructed_Daily_Totals.csv")}
        self.assertEqual(rows["2026-09-09"]["Estimate_Status"], "SKIPPED_OBSERVED_APPLE_EXISTS")
        self.assertEqual(rows["2026-09-09"]["Estimated_Apple_Minutes"], "")
        alloc_dates = {r["Date"] for r in self.read_out("05_Reconstructed_Category_Allocation.csv")}
        self.assertNotIn("2026-09-09", alloc_dates)

    def test_canonical_september_preferred_over_transcription(self):
        write_apple_daily(self.apple_dir, date(2026, 9, 23), 100)
        reference = rec.load_september_reference(
            self.reference_csv, self.apple_dir, date(2026, 9, 23), date(2026, 9, 30))
        self.assertEqual(reference[0].source, "CANONICAL_DAILY_TIME")

    def test_canonical_day_excluded_in_transcription_stays_excluded(self):
        write_apple_daily(self.apple_dir, date(2026, 9, 23), 100)
        ref = write_csv_rows(self.root / "ref_false.csv", REFERENCE_COLUMNS, [
            {"Date": "2026-09-23", "Headline_sec": 6000, "Category": "Other", "Duration_sec": 60,
             "Source_Screenshots": "x", "Use_As_Reference": "FALSE",
             "Transcription_Status": "T", "Notes": "setup day"}])
        reference = rec.load_september_reference(
            ref, self.apple_dir, date(2026, 9, 23), date(2026, 9, 30))
        self.assertEqual(reference[0].source, "CANONICAL_DAILY_TIME")
        self.assertFalse(reference[0].use_as_reference)
        self.assertEqual(reference[0].notes, "setup day")

    def test_refuses_canonical_output_dir(self):
        with self.assertRaises(rec.ReconstructionError):
            rec.ensure_safe_output_dir(rec.PROJECT_ROOT / "output" / "Daily" / "x", force=True)

    def test_refuses_existing_output_without_force(self):
        self.run_rec()
        with self.assertRaises(rec.ReconstructionError):
            self.run_rec()
        self.run_rec(force=True)


# 13. August data never modified ----------------------------------------------------------------------

class TestAugustUntouched(Fixture):
    def test_only_reconstruction_dir_changes(self):
        before = tree_hashes(self.root)
        self.run_rec()
        after = tree_hashes(self.root)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        prefix = str(Path("output") / "Analysis" / "Reconstruction" / "out")
        self.assertTrue(changed)
        self.assertTrue(all(k.startswith(prefix) for k in changed), changed)


# 14. Determinism ----------------------------------------------------------------------------------------

class TestDeterminism(Fixture):
    def test_two_runs_are_byte_identical(self):
        self.run_rec("run1")
        self.run_rec("run2")
        base = self.root / "output" / "Analysis" / "Reconstruction"
        self.assertEqual(tree_hashes(base / "run1"), tree_hashes(base / "run2"))
        audit = json.loads((base / "run1" / "14_Audit_Trail.json").read_text(encoding="utf-8"))
        self.assertIn("outputs_sha256", audit)
        self.assertEqual(audit["summary"]["method_version"], rec.METHOD_VERSION)


class TestOverlapValidation(Fixture):
    def test_overlap_excludes_missing_and_calibration_dates(self):
        self.run_rec(missing=("2026-09-01", "2026-09-10"))
        rows = self.read_out("11_Overlap_Validation.csv")
        self.assertEqual([r["Date"] for r in rows],
                         ["2026-08-31", "2026-09-11", "2026-09-12", "2026-09-13"])
        self.assertTrue(all(r["Status"] == "PENDING_APPLE_NOT_AVAILABLE" for r in rows))


if __name__ == "__main__":
    unittest.main()
