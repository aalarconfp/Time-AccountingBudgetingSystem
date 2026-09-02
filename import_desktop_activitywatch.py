"""Import a Desktop Tracker Collector export package into System Tracker.

Consumes the versioned package produced by ``export_package.py`` in the
Desktop Tracker Collector project and copies its validated ActivityWatch
data into this project's ``output/`` tree:

    <package>/Raw/ActivityWatch/DesktopPC-Andres/...   ->  output/Raw/...
    <package>/Fact/Time/ActivityWatch/DesktopPC-Andres/...  ->  output/Fact/...
    <package>/Daily/Time/ActivityWatch/DesktopPC-Andres/... ->  output/Daily/...

This module is stdlib-only and does NOT depend on the Desktop Tracker
Collector's Python environment. The export contract is vendored as
``desktop_export_contract.py`` (keep in sync with the collector's
``contract.py``).

Safety
------
- The manifest is fully re-validated (contract version, device/source
  identity, per-file checksums, CSV headers, date coverage).
- The import refuses to touch any date that falls inside a **closed**
  reporting period (a populated ``output/Integrated/Analysis/Final/<range>/``
  directory) unless ``--force`` is given, and even then it warns loudly that
  the closed period's Final outputs become stale.

Examples
--------
    python import_desktop_activitywatch.py --package "D:/Transfer/DesktopPC-Andres__2026-09-01__2026-09-30"
    python import_desktop_activitywatch.py --package export.zip --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import desktop_export_contract as contract

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
FINAL_ROOT = OUTPUT_ROOT / "Integrated" / "Analysis" / "Final"
IMPORTS_ROOT = OUTPUT_ROOT / "Imports"

EXPECTED_RAW_HEADER = list(contract.RAW_ACTIVITYWATCH_COLUMNS)
EXPECTED_FACT_HEADER = list(contract.FACT_TIME_COLUMNS)


class DesktopImportError(RuntimeError):
    """Raised when an import cannot proceed safely."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_header(path: Path) -> list[str]:
    """Return the CSV header row, tolerant of a UTF-8 BOM."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return next(reader)
        except StopIteration:
            return []


def utc_stamp() -> str:
    """Return a compact UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )


def _display_path(path: Path) -> str:
    """Return a project-relative path when possible, else the full path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# Package resolution
# --------------------------------------------------------------------------

def resolve_package_dir(raw: Path, stack: "list") -> Path:
    """Return a directory containing ``manifest.json`` for the given argument.

    Accepts a directory or a ``.zip``. Zips are extracted into a temporary
    directory whose cleanup callback is appended to ``stack``.
    """
    if not raw.exists():
        raise DesktopImportError(f"Package not found: {raw}")

    if raw.is_dir():
        directory = raw
    elif raw.suffix.lower() == ".zip":
        tmp = tempfile.mkdtemp(prefix="desktop_import_")
        stack.append(lambda: shutil.rmtree(tmp, ignore_errors=True))
        with zipfile.ZipFile(raw) as archive:
            archive.extractall(tmp)
        directory = Path(tmp)
    else:
        raise DesktopImportError(
            f"Package must be a directory or a .zip: {raw}"
        )

    if (directory / contract.MANIFEST_NAME).is_file():
        return directory

    # A zip may contain a single top-level folder.
    children = [p for p in directory.iterdir() if p.is_dir()]
    for child in children:
        if (child / contract.MANIFEST_NAME).is_file():
            return child

    raise DesktopImportError(
        f"No {contract.MANIFEST_NAME} found in {raw}."
    )


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def load_manifest(package_dir: Path) -> dict:
    """Load and identity-check the package manifest."""
    path = package_dir / contract.MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DesktopImportError(f"Cannot read {path}: {exc}") from exc

    for key in (
        "export_contract_version",
        "source",
        "device_hostname",
        "period",
        "date_coverage",
        "validation",
        "files",
    ):
        if key not in manifest:
            raise DesktopImportError(
                f"Manifest is missing required key '{key}'."
            )

    if not contract.is_compatible_contract(
        manifest["export_contract_version"]
    ):
        raise DesktopImportError(
            "Incompatible export_contract_version "
            f"{manifest['export_contract_version']!r}; this importer expects "
            f"major {contract.EXPORT_CONTRACT_VERSION}."
        )

    if manifest.get("source") != contract.SOURCE:
        raise DesktopImportError(
            f"Manifest source {manifest.get('source')!r} is not "
            f"{contract.SOURCE!r}."
        )

    if manifest.get("device_hostname") != contract.DEVICE_HOSTNAME:
        raise DesktopImportError(
            f"Manifest device_hostname {manifest.get('device_hostname')!r} "
            f"is not {contract.DEVICE_HOSTNAME!r}."
        )

    return manifest


def manifest_dates(manifest: dict) -> list[date]:
    """Return the inclusive list of expected dates from the manifest."""
    raw = manifest["date_coverage"].get("expected_dates", [])
    try:
        return [date.fromisoformat(value) for value in raw]
    except ValueError as exc:
        raise DesktopImportError(f"Malformed date in manifest: {exc}") from exc


def validate_coverage(manifest: dict) -> list[date]:
    """Confirm the manifest describes a contiguous, complete inclusive range."""
    dates = manifest_dates(manifest)
    if not dates:
        raise DesktopImportError("Manifest has no expected_dates.")

    period = manifest["period"]
    start = date.fromisoformat(period["start_date"])
    end = date.fromisoformat(period["end_date"])

    expected = contract.inclusive_dates(start, end)
    if dates != expected:
        raise DesktopImportError(
            "expected_dates is not the contiguous inclusive range "
            f"{start.isoformat()}..{end.isoformat()}."
        )

    missing = manifest["date_coverage"].get("missing_raw_dates", [])
    if missing:
        raise DesktopImportError(
            "Manifest reports missing Raw data for: " + ", ".join(missing)
        )
    return dates


def validate_files(package_dir: Path, manifest: dict) -> None:
    """Confirm every referenced file exists and matches its checksum + header."""
    problems: list[str] = []

    for entry in manifest["files"]:
        rel = entry["path"]
        source = package_dir / rel
        if not source.is_file():
            problems.append(f"missing: {rel}")
            continue
        if source.stat().st_size != entry.get("bytes"):
            problems.append(f"size mismatch: {rel}")
            continue
        if sha256_file(source) != entry.get("sha256"):
            problems.append(f"checksum mismatch: {rel}")
            continue

        header = read_header(source)
        if rel.startswith(contract.RAW_SUBPATH) and header != EXPECTED_RAW_HEADER:
            problems.append(f"unexpected Raw header: {rel}")
        elif rel.startswith(contract.FACT_SUBPATH) and header != EXPECTED_FACT_HEADER:
            problems.append(f"unexpected Fact header: {rel}")
        elif rel.startswith(contract.DAILY_SUBPATH) and not header:
            problems.append(f"empty Daily file: {rel}")

    report = manifest["validation"].get("report")
    if report and not (package_dir / report).is_file():
        problems.append(f"missing validation report: {report}")

    if problems:
        raise DesktopImportError(
            "Package contents do not match the manifest:"
            + "".join(f"\n  - {item}" for item in problems)
        )


def check_validation_status(manifest: dict, allow_unvalidated: bool) -> str:
    """Enforce the collector's validation verdict."""
    status = manifest["validation"].get("status")
    if status == contract.VALIDATION_PASS:
        return status
    if allow_unvalidated:
        print(
            f"WARNING: importing a package with validation status {status!r} "
            "(--allow-unvalidated)."
        )
        return status
    raise DesktopImportError(
        f"Collector validation status is {status!r}. Fix the collection, or "
        "re-run with --allow-unvalidated."
    )


# --------------------------------------------------------------------------
# Closed-period protection
# --------------------------------------------------------------------------

def detect_closed_periods() -> list[tuple[date, date, Path]]:
    """Return (start, end, path) for every populated final-analysis period."""
    if not FINAL_ROOT.is_dir():
        return []

    closed: list[tuple[date, date, Path]] = []
    for entry in sorted(FINAL_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if len(name) != 21 or name[10] != "_":
            continue
        try:
            start = date.fromisoformat(name[:10])
            end = date.fromisoformat(name[11:])
        except ValueError:
            continue
        if any(entry.iterdir()):
            closed.append((start, end, entry))
    return closed


def closed_period_conflicts(
    dates: list[date],
) -> list[tuple[date, date, Path]]:
    """Return closed periods that overlap any of the imported dates."""
    span = set(dates)
    conflicts = []
    for start, end, path in detect_closed_periods():
        if any(start <= d <= end for d in span):
            conflicts.append((start, end, path))
    return conflicts


# --------------------------------------------------------------------------
# Copy planning and execution
# --------------------------------------------------------------------------

def plan_copy(package_dir: Path, manifest: dict) -> dict:
    """Classify each payload file as new / replaced / unchanged."""
    new: list[str] = []
    replaced: list[str] = []
    unchanged: list[str] = []

    for entry in manifest["files"]:
        rel = entry["path"]
        target = OUTPUT_ROOT / rel
        if not target.exists():
            new.append(rel)
        elif sha256_file(target) == entry["sha256"]:
            unchanged.append(rel)
        else:
            replaced.append(rel)

    report = manifest["validation"].get("report")
    return {
        "new": new,
        "replaced": replaced,
        "unchanged": unchanged,
        "report": report,
    }


def execute_copy(package_dir: Path, manifest: dict, plan: dict) -> None:
    """Copy payload files and the validation report into output/."""
    for entry in manifest["files"]:
        rel = entry["path"]
        if rel in plan["unchanged"]:
            continue
        source = package_dir / rel
        target = OUTPUT_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256_file(target) != entry["sha256"]:
            raise DesktopImportError(f"Post-copy checksum failed for {rel}.")

    report = plan.get("report")
    if report and (package_dir / report).is_file():
        target = OUTPUT_ROOT / report
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_dir / report, target)


def write_receipt(
    *,
    package_arg: str,
    manifest: dict,
    plan: dict,
    conflicts: list[tuple[date, date, Path]],
    forced: bool,
) -> Path:
    """Persist an import receipt and return its path."""
    IMPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    period = manifest["period"]
    receipt = {
        "imported_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "source_package": package_arg,
        "export_contract_version": manifest["export_contract_version"],
        "device_hostname": manifest["device_hostname"],
        "source": manifest["source"],
        "period": period,
        "collection_created_at_utc": manifest.get("created_at_utc"),
        "validation_status": manifest["validation"].get("status"),
        "files_new": plan["new"],
        "files_replaced": plan["replaced"],
        "files_unchanged": plan["unchanged"],
        "closed_period_conflicts": [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "path": _display_path(path),
            }
            for start, end, path in conflicts
        ],
        "forced": forced,
    }
    name = (
        f"Import_Receipt_"
        f"{period['start_date']}_{period['end_date']}_{utc_stamp()}.json"
    )
    path = IMPORTS_ROOT / name
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv: "list | None" = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Import a Desktop Tracker Collector export package into "
            "System Tracker."
        )
    )
    parser.add_argument(
        "--package",
        required=True,
        type=Path,
        help="Export package directory or .zip.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report what would happen. Writes nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Proceed even if imported dates fall inside a closed period. "
            "The closed period's Final outputs become stale."
        ),
    )
    parser.add_argument(
        "--allow-unvalidated",
        action="store_true",
        help="Import even if the collector's validation status is not PASS.",
    )
    return parser.parse_args(argv)


def main(argv: "list | None" = None) -> int:
    """Run the desktop import."""
    print("# System Tracker - desktop ActivityWatch import")
    print()

    cleanup: list = []
    try:
        args = parse_args(argv)
        package_dir = resolve_package_dir(args.package, cleanup)

        manifest = load_manifest(package_dir)
        dates = validate_coverage(manifest)
        validate_files(package_dir, manifest)
        status = check_validation_status(manifest, args.allow_unvalidated)

        period = manifest["period"]
        print(f"Package  : {args.package}")
        print(f"Device   : {manifest['device_hostname']} ({manifest.get('device_key')})")
        print(
            f"Period   : {period['start_date']} -> {period['end_date']} "
            f"({period['calendar_days']} day(s))"
        )
        print(f"Contract : {manifest['export_contract_version']}")
        print(f"Validation: {status}")
        empty = manifest['date_coverage'].get('empty_dates', [])
        if empty:
            print(f"Empty days: {', '.join(empty)} (no ActivityWatch activity)")

        conflicts = closed_period_conflicts(dates)
        if conflicts:
            listed = ", ".join(
                f"{s.isoformat()}..{e.isoformat()}" for s, e, _ in conflicts
            )
            if not args.force:
                raise DesktopImportError(
                    "Imported dates fall inside closed reporting period(s): "
                    f"{listed}. Refusing to overwrite a closed period. "
                    "Re-run with --force only if you intend to invalidate "
                    "those Final outputs."
                )
            print()
            print("!" * 72)
            print(
                "WARNING: --force is overwriting source data for CLOSED "
                f"period(s): {listed}"
            )
            print("Their Final analysis outputs are now STALE and must be")
            print("regenerated and re-validated.")
            print("!" * 72)

        plan = plan_copy(package_dir, manifest)

        print()
        print("Plan:")
        print(f"  new      : {len(plan['new'])}")
        print(f"  replaced : {len(plan['replaced'])}")
        print(f"  unchanged: {len(plan['unchanged'])}")
        for rel in plan["replaced"]:
            print(f"    ~ {rel}")

        if args.dry_run:
            print()
            print("DRY RUN: no files written.")
            return 0

        execute_copy(package_dir, manifest, plan)
        receipt_path = write_receipt(
            package_arg=str(args.package),
            manifest=manifest,
            plan=plan,
            conflicts=conflicts,
            forced=args.force,
        )

        print()
        print("=" * 72)
        print("IMPORT COMPLETE")
        print("=" * 72)
        print(f"Imported : {len(plan['new']) + len(plan['replaced'])} file(s)")
        print(f"Receipt  : {receipt_path}")
        print()
        print(
            "Next: rebuild Daily/Integrated as needed and continue the "
            "System Tracker period pipeline (see docs/SYSTEM_TRACKER_RUNBOOK.md)."
        )
        return 0

    except DesktopImportError as exc:
        print(f"IMPORT FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(
            f"IMPORT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 1
    finally:
        for callback in cleanup:
            callback()


if __name__ == "__main__":
    raise SystemExit(main())
