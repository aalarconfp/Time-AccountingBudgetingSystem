# Data Collection SOP

## Objective

Collect complete, period-bounded source data before any integration or
reconciliation.

## Sources

| Source | Device | How it enters System Tracker |
|---|---|---|
| ActivityWatch — laptop | `AsusLaptop-Andres` | `activitywatch_laptop.py` → `activitywatch_pipeline.py` (run on the laptop) |
| ActivityWatch — desktop | `DesktopPC-Andres` | **imported** from the Desktop Tracker Collector via `import_desktop_activitywatch.py` |
| Apple Screen Time | iPhone | screenshots under `input/iPhone/ScreenTime/<YYYY-MM>/<YYYY-MM-DD>/` → `iphone_screen_time_*` |
| Habit / Off-Device | — | screenshots under `input/Habit/<YYYY-MM>/<YYYY-MM-DD>/` → `habit_offdevice_*` |

## Collection principles

- Preserve original exports and screenshots; never edit them.
- Keep source/device identity through every layer.
- Confirm start/end coverage; resolve gaps before close.
- Only completed local calendar days are processed (today is excluded unless a
  script is given `--include-today`).

---

## ActivityWatch — completed-day rule, idempotency, schema

Applies to both the laptop pipeline and the Desktop Tracker Collector (they
share the same `activitywatch_raw_loader.py`).

- **Completed-day rule.** By default only calendar days up to *yesterday*
  (local timezone) are loaded. The current day is incomplete and excluded.
- **Idempotent.** The raw loader keys on `AW_Event_ID`; re-running never
  duplicates events. Backfills may safely overlap existing dates.
- **Empty days.** If ActivityWatch returns zero events for a date, no CSV is
  written — "no data collected" stays distinct from "collected, zero activity".
- **Read-only.** The loader never inserts, modifies, or deletes ActivityWatch
  events.
- **Raw schema** (`output/Raw/ActivityWatch/<device>/Raw_ActivityWatch_<date>.csv`,
  UTF-8 with BOM), 12 columns:

  ```
  Date, Start, End, Duration_sec, Device, Source, Bucket,
  AW_Event_ID, App, Window_Title, AW_Category, AW_Subcategory
  ```

  (August 2026 Raw files predate the current loader and carry a 14-column
  legacy schema; that period is closed and not re-collected.)

### Laptop

Run on `AsusLaptop-Andres`:

```powershell
python .\activitywatch_laptop.py --start-date "<START>" --end-date "<END>" --force
python .\activitywatch_pipeline.py --month "<YYYY-MM>"    # or repeated --date
```

`activitywatch_pipeline.py` chains `activitywatch_raw_loader.py` →
`fact_time_builder.py` → `fact_time_validator.py` for the laptop.

### Desktop — import a validated package

Desktop ActivityWatch is collected by the **Desktop Tracker Collector**
(`../Desktop Tracker Collector/`), which produces a versioned export package.
Machine facts for the desktop live in that project's `docs/DESKTOP_MACHINE.md`.

```powershell
python .\import_desktop_activitywatch.py --package "<package dir or .zip>" --dry-run
python .\import_desktop_activitywatch.py --package "<package dir or .zip>"
```

The importer re-validates the manifest (export-contract version, device =
`DesktopPC-Andres`, source = ActivityWatch, per-file SHA-256, Raw/Fact CSV
headers, contiguous inclusive coverage, collector validation status = PASS) and
**refuses any date that falls inside a closed reporting period** unless
`--force`. It lands data in `output/Raw|Fact|Daily/.../DesktopPC-Andres/` and
writes `output/Imports/Import_Receipt_<range>_<UTC>.json`.

Human review of the receipt: confirm the period, `files_new` / `files_replaced`,
`empty_dates`, and `closed_period_conflicts` (should be empty).

---

## Apple Screen Time

Save the original screenshots; process them through `iphone_screen_time_ingest.py`
and the review → promote → build steps in `SYSTEM_TRACKER_RUNBOOK.md` Phase C2.
Never modify final Apple records to compensate for unrelated ActivityWatch
attribution corrections.

## Habit / Off-Device

Save the screenshots; process through `habit_offdevice_ingest.py` /
`habit_offdevice_builder.py`. Review manually entered activity for completeness,
duplicates, overstatement, and period boundaries.

## Collection sign-off  *(human gate)*

- [ ] Laptop ActivityWatch collected and pipelined.
- [ ] Desktop package imported; import receipt reviewed.
- [ ] Apple Screen Time screenshots present for every date.
- [ ] Habit screenshots present for every date.
- [ ] No unexplained source gaps.
- [ ] Device/source identity correct throughout.
