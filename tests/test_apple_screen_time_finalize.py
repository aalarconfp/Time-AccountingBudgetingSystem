"""Unit tests for apple_screen_time_finalize and the rebuild 'add category' correction."""

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import apple_screen_time_finalize as fin  # noqa: E402
import iphone_screen_time_rebuild as rebuild  # noqa: E402

ALLOC_COLUMNS = [
    "Date", "Source", "Category", "Subcategory", "Duration_sec", "Event_Count",
    "Allocation_Type", "Evidence_Type", "Evidence_Source", "Source_Detail",
    "Estimation_Method", "Category_Allocation", "Category_Model", "Category_Share",
    "Category_History", "Current_Period_Validation", "Calibration_Version",
    "Opal_Report_ID", "Review_Status",
]
RECORD_COLUMNS = [
    "Date", "Opal_Report_ID", "Opal_Source_Screenshot", "Opal_Minutes", "Calibration_Minutes",
    "Estimated_Apple_Minutes", "Estimated_Apple_Seconds", "Estimate_Status", "Review_Status",
    "Review_Reasons",
]


def write_csv(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_reconstruction(root: Path, days=("2026-09-01", "2026-09-02"), review=False) -> Path:
    recon = root / "recon"
    records, alloc = [], []
    for d in days:
        minutes = 100
        records.append({
            "Date": d, "Opal_Report_ID": "R1", "Opal_Source_Screenshot": "2026-09/Opal/B.PNG",
            "Opal_Minutes": 71, "Calibration_Minutes": 28.6, "Estimated_Apple_Minutes": minutes,
            "Estimated_Apple_Seconds": minutes * 60, "Estimate_Status": "ESTIMATED",
            "Review_Status": "REVIEW" if review else "READY", "Review_Reasons": "",
        })
        for cat, sec in (("Social Networking", 4000), ("Utilities", 2000), ("Games", 0)):
            alloc.append({
                "Date": d, "Source": "iphone", "Category": cat, "Subcategory": cat,
                "Duration_sec": sec, "Event_Count": 0, "Allocation_Type": "Estimated",
                "Evidence_Type": "Opal_Calibrated_Estimate",
                "Evidence_Source": "Opal + August Apple Screen Time calibration",
                "Source_Detail": "AppleScreenTime_Estimated", "Estimation_Method": "m",
                "Category_Allocation": "Historical Apple category distribution",
                "Category_Model": "HISTORICAL_OVERALL_POOLED", "Category_Share": 0.5,
                "Category_History": "h", "Current_Period_Validation": "v",
                "Calibration_Version": "V", "Opal_Report_ID": "R1", "Review_Status": "READY",
            })
    write_csv(recon / "04_Reconstructed_Daily_Totals.csv", RECORD_COLUMNS, records)
    write_csv(recon / "05_Reconstructed_Category_Allocation.csv", ALLOC_COLUMNS, alloc)
    audit = {"outputs_sha256": {
        n: hashlib.sha256((recon / n).read_bytes()).hexdigest()
        for n in ("04_Reconstructed_Daily_Totals.csv", "05_Reconstructed_Category_Allocation.csv")
    }}
    (recon / "14_Audit_Trail.json").write_text(json.dumps(audit), encoding="utf-8")
    return recon


def write_observed(fact_dir: Path, daily_dir: Path, day: str, visible: int, residual: int,
                   headline: int | None = None):
    rows = [
        {"Date": day, "Source": "iphone", "Category": "Social Networking",
         "Subcategory": "Social Networking", "Duration_sec": visible, "Event_Count": 1,
         "Allocation_Type": "Observed", "Evidence_Type": "Apple Screen Time Category",
         "Evidence_Source": "CATEGORIES"},
        {"Date": day, "Source": "iphone", "Category": "Utilities",
         "Subcategory": "Screen Time / System", "Duration_sec": residual, "Event_Count": 1,
         "Allocation_Type": "Derived", "Evidence_Type": "Apple Headline Screen Time Residual",
         "Evidence_Source": "TOTAL vs CATEGORIES"},
    ]
    write_csv(daily_dir / f"Daily_Time_{day}.csv", fin.DAILY_COLUMNS, rows)
    write_csv(fact_dir / f"Fact_Time_{day}.csv", fin.FACT_COLUMNS, [{**r, "App": ""} for r in rows])
    headline = visible + residual if headline is None else headline
    (daily_dir / f"Daily_Time_{day}.metadata.json").write_text(json.dumps({
        "reconciliation": {"headline_seconds": headline,
                           "status": "HEADLINE_EXCEEDS_VISIBLE_CATEGORIES"}}), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fact = self.root / "Fact"
        self.daily = self.root / "Daily"
        self.recon = make_reconstruction(self.root)

    def tearDown(self):
        self.tmp.cleanup()


class TestPromote(Base):
    def test_promote_writes_estimated_canonical_files(self):
        receipts = fin.promote(self.recon, self.fact, self.daily)
        self.assertEqual([r["status"] for r in receipts], ["NEW", "NEW"])
        rows = fin.read_csv(self.daily / "Daily_Time_2026-09-01.csv")
        self.assertEqual(list(rows[0].keys()), fin.DAILY_COLUMNS)
        self.assertEqual({r["Allocation_Type"] for r in rows}, {"Estimated"})
        self.assertNotIn("Games", {r["Category"] for r in rows})  # zero rows dropped
        self.assertEqual(sum(int(r["Duration_sec"]) for r in rows), 6000)
        fact = fin.read_csv(self.fact / "Fact_Time_2026-09-01.csv")
        self.assertEqual(list(fact[0].keys()), fin.FACT_COLUMNS)
        self.assertEqual({r["App"] for r in fact}, {""})
        meta = json.loads((self.daily / "Daily_Time_2026-09-01.metadata.json").read_text())
        self.assertEqual(meta["evidence_class"], "ESTIMATED")
        self.assertEqual(meta["provenance"]["category_model"], "HISTORICAL_OVERALL_POOLED")
        self.assertNotIn("reconciliation", meta)

    def test_rerun_is_unchanged(self):
        fin.promote(self.recon, self.fact, self.daily)
        receipts = fin.promote(self.recon, self.fact, self.daily)
        self.assertEqual({r["status"] for r in receipts}, {"UNCHANGED"})

    def test_never_overwrites_observed_data(self):
        write_observed(self.fact, self.daily, "2026-09-02", 5000, 100)
        before = (self.daily / "Daily_Time_2026-09-02.csv").read_bytes()
        with self.assertRaises(fin.FinalizeError):
            fin.promote(self.recon, self.fact, self.daily)
        self.assertEqual((self.daily / "Daily_Time_2026-09-02.csv").read_bytes(), before)
        # All-or-nothing: the other date was not written either.
        self.assertFalse((self.daily / "Daily_Time_2026-09-01.csv").exists())

    def test_tampered_reconstruction_refused(self):
        path = self.recon / "05_Reconstructed_Category_Allocation.csv"
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaises(fin.FinalizeError):
            fin.promote(self.recon, self.fact, self.daily)

    def test_review_reconstruction_refused(self):
        recon = make_reconstruction(self.root / "r2", review=True)
        with self.assertRaises(fin.FinalizeError):
            fin.promote(recon, self.fact, self.daily)


class TestValidate(Base):
    def run_validate(self, end="2026-09-04"):
        return fin.validate_period(date(2026, 9, 1), date.fromisoformat(end),
                                   self.fact, self.daily, self.recon)

    def test_mixed_period_passes_and_classifies(self):
        fin.promote(self.recon, self.fact, self.daily)
        write_observed(self.fact, self.daily, "2026-09-03", 5000, 300)
        write_observed(self.fact, self.daily, "2026-09-04", 1000, 4000)  # residual majority
        result = self.run_validate()
        status = {r["Date"]: (r["Apple_Status"], r["Review_Status"]) for r in result["rows"]}
        self.assertEqual(status["2026-09-01"], ("ESTIMATED", "PASS"))
        self.assertEqual(status["2026-09-03"], ("OBSERVED", "PASS"))
        self.assertEqual(status["2026-09-04"], ("OBSERVED", "REVIEW"))
        self.assertEqual(result["estimated_days"], 2)
        self.assertEqual(result["observed_days"], 2)
        self.assertEqual(result["fail_days"], [])
        self.assertAlmostEqual(result["estimated_minutes"], 200)

    def test_missing_date_detected(self):
        fin.promote(self.recon, self.fact, self.daily)
        result = self.run_validate(end="2026-09-03")
        self.assertEqual(result["missing_days"], ["2026-09-03"])

    def test_foreign_date_and_mixed_types_fail(self):
        fin.promote(self.recon, self.fact, self.daily)
        path = self.daily / "Daily_Time_2026-09-01.csv"
        rows = fin.read_csv(path)
        rows[0]["Date"] = "2026-08-01"
        rows[1]["Allocation_Type"] = "Observed"
        write_csv(path, fin.DAILY_COLUMNS, rows)
        row = self.run_validate()["rows"][0]
        self.assertEqual(row["Review_Status"], "FAIL")
        self.assertIn("foreign date", row["Review_Reasons"])
        self.assertIn("non-estimated", row["Review_Reasons"])

    def test_observed_must_reconcile_to_headline(self):
        write_observed(self.fact, self.daily, "2026-09-03", 5000, 300, headline=9999)
        row = fin.validate_day(date(2026, 9, 3), self.fact, self.daily, {})
        self.assertEqual(row["Review_Status"], "FAIL")

    def test_duplicate_rows_fail(self):
        fin.promote(self.recon, self.fact, self.daily)
        path = self.daily / "Daily_Time_2026-09-01.csv"
        rows = fin.read_csv(path)
        write_csv(path, fin.DAILY_COLUMNS, rows + rows[:1])
        row = self.run_validate()["rows"][0]
        self.assertIn("duplicate", row["Review_Reasons"])


class TestRebuildAddCategory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "AI_Evidence_Corrections.json"
        self.extraction = {"date": "2026-09-28", "categories": [
            {"apple_category": "Social", "duration_display": "2h 10m"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, corrections):
        self.path.write_text(json.dumps({"date": "2026-09-28", "corrections": corrections}))

    def test_null_old_value_adds_missing_category(self):
        self.write([{"path": "categories[Education].duration_display", "old_value": None,
                     "new_value": "8m", "reason": "visible"}])
        rebuilt, applied = rebuild.apply_corrections(self.extraction, self.path)
        self.assertEqual(applied[0]["status"], "added")
        self.assertIn({"apple_category": "Education", "duration_display": "8m"}, rebuilt["categories"])
        self.assertEqual(len(self.extraction["categories"]), 1)  # input not mutated

    def test_add_is_idempotent_and_conflicts_detected(self):
        self.write([{"path": "categories[Education].duration_display", "old_value": None,
                     "new_value": "8m", "reason": "visible"}])
        once, _ = rebuild.apply_corrections(self.extraction, self.path)
        _, applied = rebuild.apply_corrections(once, self.path)
        self.assertEqual(applied[0]["status"], "already_applied")
        self.write([{"path": "categories[Social].duration_display", "old_value": None,
                     "new_value": "9m", "reason": "x"}])
        with self.assertRaises(ValueError):
            rebuild.apply_corrections(self.extraction, self.path)

    def test_existing_modify_behaviour_unchanged(self):
        self.write([{"path": "categories[Social].duration_display", "old_value": "2h 10m",
                     "new_value": "2h 11m", "reason": "x"}])
        rebuilt, applied = rebuild.apply_corrections(self.extraction, self.path)
        self.assertEqual(rebuilt["categories"][0]["duration_display"], "2h 11m")
        self.assertEqual(applied[0]["status"], "applied")


class TestReconstructionIgnoresPromotedEstimates(Base):
    def test_promoted_estimate_is_not_observed(self):
        import opal_screen_time_reconstruction as rec
        fin.promote(self.recon, self.fact, self.daily)
        day = date(2026, 9, 1)
        self.assertTrue(rec.is_estimated_daily(self.daily, day))
        self.assertFalse(rec.has_observed_apple_daily(self.daily, day))
        self.assertIsNone(rec.load_apple_daily_seconds(self.daily, day))
        self.assertIsNone(rec.load_apple_category_day(self.daily, day))


if __name__ == "__main__":
    unittest.main()
