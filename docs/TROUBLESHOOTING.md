# Troubleshooting

## `SyntaxError`

Run:

    python -m py_compile ".\script.py"

Fix the syntax before running the script again.

## `NameError`

Usually indicates an incomplete replacement or function-definition mismatch.

Do not patch one line blindly.

Check the complete function and compare it with the current canonical script.

## `ValueError: No taxonomy mapping found`

Check:

1. source;
2. activity;
3. category;
4. `Dim_Activity.csv`;
5. category defaults;
6. taxonomy generation.

Then rerun:

    python ".\build_time_taxonomy.py"

## CSV field mismatch

If `csv.DictWriter` reports fields not in `fieldnames`, the code and audit
schema are inconsistent.

Fix the writer schema and row schema together.

Do not remove fields from rows merely to make the exception disappear.

## Unexpected zero attribution applied

Check whether the target category/device actually contains available time.

An attribution request may legitimately be capped at zero.

The audit must retain the unapplied amount.

## Unexpected REVIEW day

Inspect:

- daily reconciliation;
- source totals;
- adjustments;
- overlap;
- Off-Device Life;
- source coverage.

Do not automatically normalize the day.

## Analytical total > clock capacity

This is expected when source observations overlap.

Check the time-universe reconciliation rather than trying to force analytical
totals to 24 hours/day.

## Off-Device Life missing

Check:

- final analysis output;
- time-universe reconciliation;
- hierarchy generation;
- Off-Device taxonomy mapping.

Off-Device Life should be an explicit analytical category.

## Wrong taxonomy result

Change the reference taxonomy, rebuild it, validate it, and rerun the
analysis.

Do not manually edit final analytical CSVs.

## Desktop import: `IMPORT FAILED`

`import_desktop_activitywatch.py` refuses on:

- **Incompatible `export_contract_version`** — the collector and this repo are
  on different contract majors. Update the older side (`contract.py` in the
  collector; `desktop_export_contract.py` here — keep them in sync).
- **Wrong device / source** — the package is not `DesktopPC-Andres` /
  ActivityWatch. Wrong package.
- **`checksum mismatch` / `unexpected Raw|Fact header`** — the package was
  edited after export, or was produced by an old collector. Re-run
  `collect_desktop.py` + `export_package.py` on the desktop.
- **`expected_dates is not the contiguous inclusive range`** or
  **`missing Raw data`** — the collection has gaps. Re-collect the period on
  the desktop.
- **`validation status is 'FAIL'`** — the collector's Fact_Time validation
  failed. Fix it there; only use `--allow-unvalidated` with a specific reason.
- **`Imported dates fall inside closed reporting period(s)`** — the target
  dates overlap a populated `output/Integrated/Analysis/Final/<range>/`.
  Re-run with `--force` only if you intend to invalidate that period's Final
  outputs, and record why (`docs/CHANGE_CONTROL.md`, Class A).

Use `--dry-run` first to see the plan without writing anything. Every real
import writes `output/Imports/Import_Receipt_*.json`.

## Desktop collection itself fails

That is a Desktop Tracker Collector problem — see that project's
`docs/TROUBLESHOOTING.md` (machine mismatch, ActivityWatch not running,
empty days, validation failure).
