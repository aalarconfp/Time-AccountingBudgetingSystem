"""Unit tests for import_desktop_activitywatch (stdlib unittest)."""

import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desktop_export_contract as contract  # noqa: E402
import import_desktop_activitywatch as imp  # noqa: E402

RAW_HEADER = ",".join(contract.RAW_ACTIVITYWATCH_COLUMNS) + "\n"
FACT_HEADER = ",".join(contract.FACT_TIME_COLUMNS) + "\n"
DAILY_HEADER = "Date,Category,Subcategory,Duration_sec\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_package(root: Path, start="2026-09-01", end="2026-09-03") -> Path:
    """Create a minimal valid export package under ``root`` and return its dir."""
    pkg = root / contract.package_name(
        date.fromisoformat(start), date.fromisoformat(end)
    )
    dates = contract.inclusive_dates(
        date.fromisoformat(start), date.fromisoformat(end)
    )
    files = []
    for d in dates:
        raw_rel = f"{contract.RAW_SUBPATH}/{contract.raw_filename(d)}"
        fact_rel = f"{contract.FACT_SUBPATH}/{contract.fact_filename(d)}"
        daily_rel = f"{contract.DAILY_SUBPATH}/{contract.daily_filename(d)}"
        _write(pkg / raw_rel, RAW_HEADER + "2026-09-01,x,y,60,Desktop,ActivityWatch,b,e1,App,Win,Cat,Sub\n")
        _write(pkg / fact_rel, FACT_HEADER + "f1,2026-09-01,x,y,60,Desktop,ActivityWatch,b,e1,App,Win,Cat,Sub\n")
        _write(pkg / daily_rel, DAILY_HEADER + "2026-09-01,Cat,Sub,60\n")
        for rel in (raw_rel, fact_rel, daily_rel):
            p = pkg / rel
            files.append(
                {
                    "path": rel,
                    "date": d.isoformat(),
                    "bytes": p.stat().st_size,
                    "rows": 1,
                    "sha256": imp.sha256_file(p),
                }
            )

    report_rel = f"{contract.VALIDATION_SUBPATH}/{contract.validation_report_name(dates[0], dates[-1])}"
    _write(pkg / report_rel, "Checks passed: 3\nChecks failed: 0\n")

    manifest = {
        "export_contract_version": contract.EXPORT_CONTRACT_VERSION,
        "generator": contract.GENERATOR,
        "collector_version": contract.COLLECTOR_VERSION,
        "created_at_utc": "2026-09-04T00:00:00Z",
        "source": contract.SOURCE,
        "device_key": contract.DEVICE_KEY,
        "device_hostname": contract.DEVICE_HOSTNAME,
        "machine_validated": True,
        "schema": {"raw": "1.0", "fact": "1.0", "daily": "1.0"},
        "period": {
            "start_date": start,
            "end_date": end,
            "inclusive": True,
            "calendar_days": len(dates),
        },
        "date_coverage": {
            "expected_dates": [d.isoformat() for d in dates],
            "raw_dates": [d.isoformat() for d in dates],
            "fact_dates": [d.isoformat() for d in dates],
            "daily_dates": [d.isoformat() for d in dates],
            "empty_dates": [],
            "missing_raw_dates": [],
        },
        "record_counts": {"raw_events": len(dates), "fact_rows": len(dates), "daily_rows": len(dates)},
        "validation": {"status": contract.VALIDATION_PASS, "report": report_rel, "passed": 3, "failed": 0},
        "files": files,
        "environment": {"python": "3.14.0", "platform": "test", "aw_client": "x"},
    }
    _write(pkg / contract.MANIFEST_NAME, json.dumps(manifest, indent=2))
    return pkg


class BaseCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pkg = make_package(self.root)
        self._orig = (imp.OUTPUT_ROOT, imp.FINAL_ROOT, imp.IMPORTS_ROOT)
        imp.OUTPUT_ROOT = self.root / "st_output"
        imp.FINAL_ROOT = imp.OUTPUT_ROOT / "Integrated" / "Analysis" / "Final"
        imp.IMPORTS_ROOT = imp.OUTPUT_ROOT / "Imports"

    def tearDown(self):
        imp.OUTPUT_ROOT, imp.FINAL_ROOT, imp.IMPORTS_ROOT = self._orig
        self._tmp.cleanup()


class ManifestTests(BaseCase):
    def test_valid(self):
        m = imp.load_manifest(self.pkg)
        self.assertEqual(m["device_hostname"], contract.DEVICE_HOSTNAME)

    def test_missing_key(self):
        m = json.loads((self.pkg / contract.MANIFEST_NAME).read_text())
        del m["files"]
        (self.pkg / contract.MANIFEST_NAME).write_text(json.dumps(m))
        with self.assertRaises(imp.DesktopImportError):
            imp.load_manifest(self.pkg)

    def test_bad_major(self):
        m = json.loads((self.pkg / contract.MANIFEST_NAME).read_text())
        m["export_contract_version"] = "2.0"
        (self.pkg / contract.MANIFEST_NAME).write_text(json.dumps(m))
        with self.assertRaises(imp.DesktopImportError):
            imp.load_manifest(self.pkg)

    def test_wrong_device(self):
        m = json.loads((self.pkg / contract.MANIFEST_NAME).read_text())
        m["device_hostname"] = "Laptop"
        (self.pkg / contract.MANIFEST_NAME).write_text(json.dumps(m))
        with self.assertRaises(imp.DesktopImportError):
            imp.load_manifest(self.pkg)

    def test_wrong_source(self):
        m = json.loads((self.pkg / contract.MANIFEST_NAME).read_text())
        m["source"] = "Habit"
        (self.pkg / contract.MANIFEST_NAME).write_text(json.dumps(m))
        with self.assertRaises(imp.DesktopImportError):
            imp.load_manifest(self.pkg)


class CoverageTests(BaseCase):
    def test_contiguous_ok(self):
        m = imp.load_manifest(self.pkg)
        self.assertEqual(len(imp.validate_coverage(m)), 3)

    def test_non_contiguous(self):
        m = imp.load_manifest(self.pkg)
        m["date_coverage"]["expected_dates"] = ["2026-09-01", "2026-09-03"]
        with self.assertRaises(imp.DesktopImportError):
            imp.validate_coverage(m)

    def test_missing_raw_dates(self):
        m = imp.load_manifest(self.pkg)
        m["date_coverage"]["missing_raw_dates"] = ["2026-09-02"]
        with self.assertRaises(imp.DesktopImportError):
            imp.validate_coverage(m)


class FileValidationTests(BaseCase):
    def test_ok(self):
        m = imp.load_manifest(self.pkg)
        imp.validate_files(self.pkg, m)

    def test_missing_file(self):
        m = imp.load_manifest(self.pkg)
        (self.pkg / m["files"][0]["path"]).unlink()
        with self.assertRaises(imp.DesktopImportError):
            imp.validate_files(self.pkg, m)

    def test_checksum_drift(self):
        m = imp.load_manifest(self.pkg)
        target = self.pkg / m["files"][0]["path"]
        target.write_text(RAW_HEADER + "changed\n", encoding="utf-8")
        with self.assertRaises(imp.DesktopImportError):
            imp.validate_files(self.pkg, m)

    def test_bad_raw_header(self):
        m = imp.load_manifest(self.pkg)
        raw_entry = next(e for e in m["files"] if e["path"].startswith(contract.RAW_SUBPATH))
        p = self.pkg / raw_entry["path"]
        p.write_text("WRONG,HEADER\nx,y\n", encoding="utf-8")
        raw_entry["bytes"] = p.stat().st_size
        raw_entry["sha256"] = imp.sha256_file(p)
        with self.assertRaises(imp.DesktopImportError):
            imp.validate_files(self.pkg, m)


class ValidationStatusTests(BaseCase):
    def test_pass(self):
        m = imp.load_manifest(self.pkg)
        self.assertEqual(
            imp.check_validation_status(m, False), contract.VALIDATION_PASS
        )

    def test_fail_blocks(self):
        m = imp.load_manifest(self.pkg)
        m["validation"]["status"] = contract.VALIDATION_FAIL
        with self.assertRaises(imp.DesktopImportError):
            imp.check_validation_status(m, False)

    def test_fail_allowed(self):
        m = imp.load_manifest(self.pkg)
        m["validation"]["status"] = contract.VALIDATION_FAIL
        self.assertEqual(
            imp.check_validation_status(m, True), contract.VALIDATION_FAIL
        )


class ClosedPeriodTests(BaseCase):
    def _make_final(self, name: str, populated: bool = True):
        d = imp.FINAL_ROOT / name
        d.mkdir(parents=True)
        if populated:
            (d / "Final_Analysis.csv").write_text("x", encoding="utf-8")

    def test_no_final_dir(self):
        self.assertEqual(imp.closed_period_conflicts([date(2026, 9, 1)]), [])

    def test_overlap_detected(self):
        self._make_final("2026-09-01_2026-09-30")
        conflicts = imp.closed_period_conflicts(
            [date(2026, 9, 2), date(2026, 9, 3)]
        )
        self.assertEqual(len(conflicts), 1)

    def test_empty_final_dir_ignored(self):
        self._make_final("2026-09-01_2026-09-30", populated=False)
        self.assertEqual(imp.closed_period_conflicts([date(2026, 9, 2)]), [])

    def test_non_overlapping_period_ok(self):
        self._make_final("2026-08-01_2026-08-31")
        self.assertEqual(imp.closed_period_conflicts([date(2026, 9, 2)]), [])


class PlanAndCopyTests(BaseCase):
    def test_plan_new_then_unchanged_then_replaced(self):
        m = imp.load_manifest(self.pkg)
        plan = imp.plan_copy(self.pkg, m)
        self.assertEqual(len(plan["new"]), 9)  # 3 days * (raw+fact+daily)
        self.assertEqual(plan["replaced"], [])
        self.assertEqual(plan["unchanged"], [])

        imp.execute_copy(self.pkg, m, plan)
        for entry in m["files"]:
            self.assertTrue((imp.OUTPUT_ROOT / entry["path"]).is_file())

        plan2 = imp.plan_copy(self.pkg, m)
        self.assertEqual(len(plan2["unchanged"]), 9)

        first = imp.OUTPUT_ROOT / m["files"][0]["path"]
        first.write_text(RAW_HEADER + "mutated\n", encoding="utf-8")
        plan3 = imp.plan_copy(self.pkg, m)
        self.assertEqual(plan3["replaced"], [m["files"][0]["path"]])

    def test_receipt_written(self):
        m = imp.load_manifest(self.pkg)
        plan = imp.plan_copy(self.pkg, m)
        path = imp.write_receipt(
            package_arg="pkg", manifest=m, plan=plan, conflicts=[], forced=False
        )
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text())
        self.assertEqual(data["device_hostname"], contract.DEVICE_HOSTNAME)
        self.assertEqual(len(data["files_new"]), 9)


class MainTests(BaseCase):
    def test_dry_run_writes_nothing(self):
        rc = imp.main(["--package", str(self.pkg), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(imp.OUTPUT_ROOT.exists())

    def test_full_import(self):
        rc = imp.main(["--package", str(self.pkg)])
        self.assertEqual(rc, 0)
        raw_dir = imp.OUTPUT_ROOT / contract.RAW_SUBPATH
        self.assertEqual(len(list(raw_dir.glob("*.csv"))), 3)
        self.assertTrue(any(imp.IMPORTS_ROOT.glob("Import_Receipt_*.json")))

    def test_closed_period_refused_then_forced(self):
        (imp.FINAL_ROOT / "2026-09-01_2026-09-30").mkdir(parents=True)
        (imp.FINAL_ROOT / "2026-09-01_2026-09-30" / "Final_Analysis.csv").write_text("x")

        rc = imp.main(["--package", str(self.pkg)])
        self.assertEqual(rc, 1)
        self.assertFalse((imp.OUTPUT_ROOT / contract.RAW_SUBPATH).exists())

        rc2 = imp.main(["--package", str(self.pkg), "--force"])
        self.assertEqual(rc2, 0)
        self.assertTrue((imp.OUTPUT_ROOT / contract.RAW_SUBPATH).exists())

    def test_zip_package(self):
        zip_path = self.root / "export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in self.pkg.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(self.pkg.parent))
        rc = imp.main(["--package", str(zip_path), "--dry-run"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
