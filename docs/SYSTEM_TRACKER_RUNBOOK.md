# System Tracker Runbook

Version: 2.0
Status: Canonical operational runbook
Supersedes: `docs/history/PERIOD_PIPELINE_RUNBOOK_FINAL.md` (archived)

This is the single source of truth for running a reporting period. Do not
reconstruct the process from chat history or from the archived runbook. Follow
this document and `docs/PERIOD_CLOSE_CHECKLIST.md`.

---

## 0. Architecture

Two projects:

```
DESKTOP PC                          LAPTOP / central
──────────                          ────────────────
Desktop Tracker Collector           System Tracker  (this repo)
  ActivityWatch → Raw → Fact_Time     ├── import desktop package
  → Daily_Time → validate → export    ├── laptop ActivityWatch
        │                             ├── iPhone Screen Time
        │  portable export package    ├── Habit / Off-Device
        └────────────────────────────►│
                                      ▼
                        Integrated Daily Time
                                      ▼
                        Integration / Reconciliation
                                      ▼
                        Final Analysis
                          ├── Detail Analysis
                          ├── EDA
                          ├── Standard Report
                          └── Period Close
```

- **Desktop Tracker Collector** (`../Desktop Tracker Collector/`, separate repo)
  owns desktop ActivityWatch collection only. See its `docs/COLLECTION_RUNBOOK.md`.
- **System Tracker** owns cross-device integration and all analysis.
- The desktop no longer needs this repo to collect ActivityWatch data.

## Accounting model (established — do not redesign)

```
Clock Capacity  =  Unique Tracked Time  +  Off-Device Life
Unique Tracked Time  =  Corrected Tracked Time  -  Tracked Overlap
```

- Analytical source totals may exceed clock capacity because multiple devices
  observe the same elapsed time. This is not automatically an error.
- Off-Device Life is intentional analytical time (human-life maintenance not
  captured by device telemetry). It is not "missing" time.
- Taxonomy: 12 canonical categories, 7 domains, 5 energies, 3 goals. EDA
  taxonomy candidates are diagnostic, never automatic changes.

## Period semantics

A period is an **inclusive** date range `START_DATE .. END_DATE`. Every command
takes `--start-date` / `--end-date` (some also `--date` or `--month`). Examples
in this runbook use a full month; any inclusive range works.

```
START_DATE = 2026-09-01
END_DATE   = 2026-09-30
MONTH      = 2026-09
Clock capacity = calendar_days × 24 h
```

Only **completed local calendar days** are processed. The current day is
excluded unless a script is given `--include-today`.

---

## Phase A — Prepare

### A1. Define the period

Record start date, end date, label (`<START>_<END>`), expected calendar days,
and clock capacity.

### A2. Python environment

```powershell
.\.venv\Scripts\Activate.ps1
python --version
```

Compile the core scripts:

```powershell
python -m py_compile `
    build_time_taxonomy.py fact_time_validator.py daily_time_builder.py `
    activitywatch_pipeline.py import_desktop_activitywatch.py `
    iphone_screen_time_ingest.py iphone_screen_time_promote.py `
    iphone_screen_time_builder.py habit_offdevice_ingest.py `
    habit_offdevice_builder.py integration_analysis.py `
    integration_human_review.py integrated_daily_time_builder.py `
    habit_manual_adjustments.py final_analysis.py detail_analysis.py `
    exploratory_analysis.py standard_report.py period_close_validator.py
```

### A3. Confirm inputs / outputs exist

Source folders, `output/Reference/Taxonomy/`, `input/Integrated/*.csv`, and the
reporting-period destination directories.

---

## Phase B — Collect sources

### B1. ActivityWatch — laptop  *(run on `AsusLaptop-Andres`)*

```powershell
python .\activitywatch_laptop.py --start-date "2026-09-01" --end-date "2026-09-30" --force
python .\activitywatch_pipeline.py --month "2026-09"
```

`activitywatch_pipeline.py` runs `activitywatch_raw_loader.py` →
`fact_time_builder.py` → `fact_time_validator.py` for the laptop. It is
laptop-only.

### B2. ActivityWatch — desktop  *(import from Desktop Tracker Collector)*

On the desktop, run the collector (`collect_desktop.py` + `export_package.py`);
transfer the package; then here:

```powershell
python .\import_desktop_activitywatch.py --package "<package directory or .zip>" --dry-run
python .\import_desktop_activitywatch.py --package "<package directory or .zip>"
```

The importer re-validates the manifest (contract version, device/source,
per-file checksums, CSV headers, contiguous inclusive coverage, collector
validation status) and **refuses any date inside a closed period** unless
`--force`. It writes `output/Raw|Fact|Daily/.../DesktopPC-Andres/` and an
`output/Imports/Import_Receipt_*.json`. Human review: confirm the receipt's
period, `files_new`/`files_replaced`, and `empty_dates`.

### B3. Apple Screen Time — evidence

Save the original iPhone screenshots (do not alter them) under
`input\iPhone\ScreenTime\2026-09\2026-09-DD\`.

### B4. Habit / Off-Device — evidence

Save Habit screenshots under `input\Habit\2026-09\2026-09-DD\`. Review that all
legitimate offline activity for the period is recorded (meals, showering,
commuting, conversations, pauses, offline work/study).

### B5. Validate source coverage  *(human gate)*

Check for: missing dates, duplicate files, impossible durations, unexpected
device gaps, unexpected source changes. Stop and investigate material gaps
before processing.

---

## Phase C — Process sources

### C1. Laptop / desktop Daily_Time

Laptop `Daily_Time` is produced by `activitywatch_pipeline.py` (B1). Desktop
`Daily_Time` arrives in the import package (B2). If either is missing for a
date, build it explicitly:

```powershell
python .\daily_time_builder.py --source asus_laptop --start-date "2026-09-01" --end-date "2026-09-30"
python .\daily_time_builder.py --source desktop      --start-date "2026-09-01" --end-date "2026-09-30"
```

Optional explicit Fact validation:

```powershell
python .\fact_time_validator.py --source asus_laptop --start-date "2026-09-01" --end-date "2026-09-30"
python .\fact_time_validator.py --source desktop      --start-date "2026-09-01" --end-date "2026-09-30"
```

### C2. iPhone Screen Time

```powershell
python .\iphone_screen_time_ingest.py --month "2026-09" --dry-run      # coverage check
python .\iphone_screen_time_ingest.py --month "2026-09"                # OpenAI extraction ($ cost; needs OPENAI_API_KEY)
```

**Human evidence review (gate):** compare each candidate extraction with the
original screenshot — total Screen Time, category totals, unresolved residual,
date. Do not promote a candidate that does not match the evidence.

```powershell
python .\iphone_screen_time_promote.py --month "2026-09" --date "2026-09-01" [--date ...]   # reviewed dates
python .\iphone_screen_time_categorize_unresolved.py --month "2026-09" --date "2026-09-01"  # positive residuals only
python .\iphone_screen_time_builder.py --month "2026-09" --date "2026-09-01" [--date ...] --force
```

`iphone_screen_time_rebuild.py --month "2026-09"` is a zero-API rebuild after
taxonomy/logic changes that need no new screenshots.

### C3. Habit / Off-Device

```powershell
python .\habit_offdevice_ingest.py --month "2026-09" --dry-run
python .\habit_offdevice_ingest.py --month "2026-09"
```

**Human review (gate):** check the extraction for completeness, duplicates,
overstatement, and period boundaries. Then:

```powershell
python .\habit_offdevice_builder.py --month "2026-09" --date "2026-09-01" [--date ...] --force
```

### C4. Taxonomy

```powershell
python .\build_time_taxonomy.py
```

Expected: `TIME TAXONOMY VALIDATION PASSED`. Taxonomy changes belong in
`output/Reference/Taxonomy/` reference CSVs, never in generated analysis CSVs.

---

## Phase D — Integrate

### D1. Build Integrated Daily Time

```powershell
python .\integrated_daily_time_builder.py `
    --start-date "2026-09-01" --end-date "2026-09-30" `
    --manual-input ".\input\Integrated\Manual_Adjustments.csv" `
    --classification-input ".\input\Integrated\Classification_Weights.csv"
```

Produces `output/Integrated/Integrated_Daily_Time_<date>.csv`. This must run
**before** integration analysis.

### D2. Preliminary integration analysis + human-review template

```powershell
python .\integration_analysis.py --start-date "2026-09-01" --end-date "2026-09-30" --unaccounted-target-hours 3
python .\integration_human_review.py --start-date "2026-09-01" --end-date "2026-09-30"
```

### D3. Manual integration review  *(human gate)*

Review and edit as applicable:

```
input\Integrated\Habit_Manual_Adjustments.csv
input\Integrated\Manual_Adjustments.csv
input\Integrated\Classification_Weights.csv
output\Integrated\Analysis\Human_Review\Integration_Classification_Removals.csv
```

Rules: every adjustment needs a reason; do not delete records silently; do not
edit generated final CSVs; do not use an adjustment to hide a source-processing
bug; do not reduce one device merely because another observed the same time.
For the Brother/Desktop correction: target ActivityWatch Desktop / Uncategorized
when available; do **not** reduce Apple Screen Time; apply only the amount
actually available; preserve unapplied time in the audit.

### D4. Apply Habit / manual adjustments

```powershell
python .\habit_manual_adjustments.py `
    --start-date "2026-09-01" --end-date "2026-09-30" `
    --adjustment-file ".\input\Integrated\Habit_Manual_Adjustments.csv" --force
```

Re-run D1 if the adjustments changed the integrated inputs.

---

## Phase E — Final reconciliation

### E1. Run

```powershell
python .\final_analysis.py --start-date "2026-09-01" --end-date "2026-09-30" --force
```

Output: `output/Integrated/Analysis/Final/2026-09-01_2026-09-30/` containing
`Final_Analysis_*`, `Final_Analysis_By_[Device_]Category_Subcategory_Domain_Energy_Goal_*`,
`Final_Source_Reconciliation_*`, `Final_Daily_Reconciliation_*`,
`Final_Correction_Audit_*`, `Final_Attribution_Removals_*`,
`Final_Time_Universe_Reconciliation_*`, `Final_Reconciliation_*`,
`Final_Analysis_Report_*.txt`, plus a nested `Integrated/` copy of the daily
inputs and the `Integration_*` diagnostic files.

### E2. Review  *(human gate)*

- **Correction audit** — every adjustment shows requested / applied / unapplied
  / direction / status. No correction silently manufactures time.
- **Daily reconciliation** — investigate every `REVIEW` day. A REVIEW flag is a
  condition to understand, not an automatic failure.
- **Time universe** — `Unique Tracked + Off-Device Life = Clock Capacity`;
  tracked overlap excluded from unique tracked.
- **Attribution / classification removals**, **overlap**, **uncovered time**,
  **Off-Device Life**, **unexpected source/device totals**.

---

## Phase F — Hierarchy, EDA, taxonomy loop

### F1. Detail hierarchy

```powershell
python .\detail_analysis.py --start-date "2026-09-01" --end-date "2026-09-30" --force
```

Review across `Device → Category → Subcategory → Domain → Energy → Goal` and the
category-first levels. Off-Device Life must have meaningful dimensions at the
deepest level.

### F2. EDA

```powershell
python .\exploratory_analysis.py --start-date "2026-09-01" --end-date "2026-09-30" --force
```

Diagnostic only. Investigate large contributors, concentration, Uncategorized,
generic buckets, taxonomy candidates, domain/energy/goal distributions. A large
node is not automatically a taxonomy problem.

### F3. Taxonomy review loop  *(only for a genuine mapping error)*

```
EDA finding → human review → edit output/Reference/Taxonomy/ →
build_time_taxonomy.py → final_analysis.py → detail_analysis.py →
exploratory_analysis.py → standard_report.py → period_close_validator.py
```

Never patch a generated CSV to change analytical meaning.

---

## Phase G — Report and close

### G1. Standard Report

```powershell
python .\standard_report.py --start-date "2026-09-01" --end-date "2026-09-30" --force
```

Intentionally concise: where time went; investment / maintenance / consumption
balance; recovery; discretionary drains; next-period attention areas. Deeper
questions belong in EDA.

### G2. Period-close validation

```powershell
python .\period_close_validator.py `
    --start-date "2026-09-01" --end-date "2026-09-30" `
    --require-eda --require-standard-report
```

Success ends with `RESULT: PERIOD CLOSE VALIDATION PASSED.` The validator checks
accounting and structural integrity; it does not require EDA text markers.

### G3. Period-Close Checklist

Execute `docs/PERIOD_CLOSE_CHECKLIST.md` in full. This is the mandatory final
gate before archiving and historical integration.

### G4. Archive

Preserve source evidence, the desktop import receipt, integrated data, final
analysis, reconciliation files, hierarchy, EDA, Standard Report, adjustment
audit, taxonomy version/state, and period notes. Never overwrite a closed
period without recording why.

---

## Phase H — Historical, comparison, commit

### H1. Historical integration

Separate from period reconciliation. Use `docs/HISTORICAL_DATA_INTEGRATION.md`.
Do it after the current period is internally closed. Do not mix historical
consolidation into `final_analysis.py`.

### H2. Period-to-period comparison (optional)

```powershell
python .\variation_analysis.py `
    --period-a-start 2026-08-01 --period-a-end 2026-08-31 `
    --period-b-start 2026-09-01 --period-b-end 2026-09-30
```

Compares two frozen final-analysis periods → `output/Integrated/Analysis/Variation/`.

### H3. Commit

```powershell
git status
git diff --stat
git diff
git status --short
```

Add only intended code/doc changes. `input/` and `output/` are git-ignored;
never `git add .` blindly. Commit period and process changes together when
appropriate.

---

## Canonical command order

```
laptop ActivityWatch  +  import desktop package
        ↓
daily_time_builder (as needed)  +  fact_time_validator
        ↓
iPhone: ingest → review → promote → categorize residuals → builder
Habit:  ingest → review → builder
        ↓
build_time_taxonomy
        ↓
integrated_daily_time_builder            ← produces Integrated_Daily_Time
        ↓
integration_analysis  +  integration_human_review
        ↓
manual review → habit_manual_adjustments → (rebuild integrated daily)
        ↓
final_analysis
        ↓
detail_analysis → exploratory_analysis
        ↓
(taxonomy loop if a mapping is genuinely wrong)
        ↓
standard_report
        ↓
period_close_validator
        ↓
Period-Close Checklist → archive → historical integration → commit
```

## Which machine runs what

| Step | Machine |
|---|---|
| `activitywatch_laptop.py`, `activitywatch_pipeline.py` | Laptop (`AsusLaptop-Andres`) — needs the local ActivityWatch server |
| Desktop collection (`collect_desktop.py`, `export_package.py`) | Desktop (`DesktopPC-Andres`) — separate project |
| `import_desktop_activitywatch.py` and everything downstream | Laptop / central — pure file processing |
| iPhone / Habit ingest | Laptop / central — needs `OPENAI_API_KEY` + internet |

---

## Non-negotiable rules

1. Do not manually edit generated analytical CSVs.
2. Do not reduce Apple Screen Time for the Brother/Desktop correction.
3. Do not treat Off-Device Life as missing time.
4. Do not force analytical activity to equal clock capacity.
5. Do not change taxonomy merely because a node is large.
6. Do not diagnose burnout from a single period.
7. Do not discard unapplied adjustment time.
8. Do not make undocumented manual changes to a closed period.
9. Do not import desktop data that overlaps a closed period without recording why.
10. Do not let the Standard Report become the EDA.
11. Do not rely on chat history — a closed period must be reproducible from this runbook.
