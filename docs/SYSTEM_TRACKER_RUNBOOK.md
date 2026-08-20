# System Tracker Runbook

Version: 1.0  
Status: Operational baseline  
Baseline period: 2026-08-01 → 2026-08-15

## Purpose

This is the canonical operating procedure for a reporting period.

Do not rely on memory or chat history to reproduce the process. Follow this
runbook and the period-close checklist.

---

## Phase A — Prepare

### Step 1 — Define the reporting period

Record:

- start date
- end date
- reporting-period label
- expected calendar days

For a 15-day period:

    Calendar days × 24h = clock capacity

### Step 2 — Prepare the Python environment

Confirm the project virtual environment is active.

Compile the principal scripts:

    python -m py_compile ".\build_time_taxonomy.py"
    python -m py_compile ".\final_analysis.py"
    python -m py_compile ".\exploratory_analysis.py"
    python -m py_compile ".\standard_report.py"

### Step 3 — Confirm project inputs and outputs

Confirm source folders, reference taxonomy, integration output folders, and
the reporting-period destination exist.

---

## Phase B — Collect sources

### Step 4 — Collect ActivityWatch laptop data

Follow `ACTIVITYWATCH_LAPTOP.md`.

Verify complete coverage for the reporting period.

### Step 5 — Collect ActivityWatch desktop data

Follow `ACTIVITYWATCH_DESKTOP.md`.

Verify complete coverage and correct device identity.

### Step 6 — Collect Apple Screen Time

Export/copy the period data according to the Apple Screen Time procedure.

Do not manually alter the source export.

### Step 7 — Collect Habit / Off-Device data

Verify all manually recorded activities for the period.

Include legitimate offline activities such as meals, showering, commuting,
conversations, pauses, and other maintenance where tracked.

### Step 8 — Validate source coverage

Check:

- missing dates
- duplicate files
- impossible durations
- unexpected device gaps
- unexpected source changes

Stop and investigate material source gaps before reconciliation.

---

## Phase C — Process and integrate

### Step 9 — Run source-specific processors

Run the appropriate daily builders for each source.

Never manually construct the integrated CSV.

### Step 10 — Integrate daily source data

Generate the integrated daily files for the reporting period.

### Step 11 — Review raw integration

Confirm:

- expected number of daily files
- expected source counts
- expected device/source identity
- no obvious duplicate ingestion
- no unexplained missing dates

---

## Phase D — Reconciliation

### Step 12 — Review and enter period adjustments

Review known overstatements and attribution corrections.

Classification removal means the activity/category itself was overstated.

Attribution removal/redirect means the time should not be attributed to the
current analytical owner.

For the established Brother/Desktop correction:

- target ActivityWatch Desktop / Uncategorized when available;
- do not reduce Apple Screen Time;
- apply only the amount actually available;
- preserve unapplied time in the audit.

### Step 13 — Build and validate taxonomy

Run:

    python ".\build_time_taxonomy.py"

Expected result:

    TIME TAXONOMY VALIDATION PASSED

Taxonomy changes belong in the reference taxonomy, not in ad-hoc final CSV edits.

### Step 14 — Run final reconciliation

Run:

    python ".\final_analysis.py" `
        --start-date "YYYY-MM-DD" `
        --end-date "YYYY-MM-DD" `
        --force

### Step 15 — Review correction audit

Inspect `Final_Correction_Audit_*.csv`.

Confirm each adjustment has:

- requested amount
- applied amount
- unapplied amount
- direction/type
- status/reason

No correction should silently manufacture time.

### Step 16 — Review daily reconciliation

Inspect `Final_Daily_Reconciliation_*.csv`.

Investigate REVIEW days.

A REVIEW flag is a condition requiring inspection, not automatically a failed
period.

---

## Phase E — Accounting and hierarchy validation

### Step 17 — Validate the time universe

Inspect `Final_Time_Universe_Reconciliation_*.csv`.

The core relationship is:

    Unique Tracked + Off-Device Life = Clock Capacity

Tracked overlap is excluded from unique tracked time.

Analytical activity may exceed capacity because analytical sources overlap.

### Step 18 — Validate the analytical hierarchy

Inspect the hierarchy output:

    Device
    Category
    Subcategory
    Domain
    Energy
    Goal

and the combined hierarchy levels.

Confirm that Off-Device Life has its intended dimensions.

---

## Phase F — Exploration

### Step 19 — Run exploratory analysis

Run:

    python ".\exploratory_analysis.py" `
        --start-date "YYYY-MM-DD" `
        --end-date "YYYY-MM-DD" `
        --force

EDA is diagnostic. It does not automatically change taxonomy.

### Step 20 — Review taxonomy candidates

Review large nodes, Uncategorized nodes, generic buckets, and unusual
concentrations.

A large node is not automatically a taxonomy problem.

### Step 21 — Apply only intentional taxonomy changes

If a mapping is genuinely wrong:

1. change the taxonomy/reference mapping;
2. rebuild and validate taxonomy;
3. rerun final analysis;
4. rerun EDA;
5. rerun Standard Report.

Do not patch final CSVs manually.

---

## Phase G — Reporting and close

### Step 22 — Run the Standard Report

Run:

    python ".\standard_report.py" `
        --start-date "YYYY-MM-DD" `
        --end-date "YYYY-MM-DD" `
        --force

The Standard Report is intentionally concise.

### Step 23 — Execute the Period-Close Checklist

Use `PERIOD_CLOSE_CHECKLIST.md`.

This is mandatory. It is the final operational gate before archiving and
historical integration.

### Step 24 — Archive the period

Preserve:

- source snapshots/exports as appropriate;
- integrated data;
- final analysis;
- reconciliation files;
- EDA;
- Standard Report;
- adjustment audit;
- taxonomy version/state;
- period notes.

Do not overwrite a closed period without recording why.

---

## Phase H — Historical and versioned reporting
Give me 
### Step 25 — Integrate with historical data

Historical integration is a separate process from period reconciliation.

For the initial implementation, the historical dataset covers approximately
one year and may require a controlled manual integration.

Use:

    docs/HISTORICAL_DATA_INTEGRATION.md

Do not mix historical consolidation with source correction logic.

### Step 26 — Commit and document the period

Before committing:

- verify the checklist is complete;
- document intentional taxonomy changes;
- document reconciliation exceptions;
- document any manual historical integration work;
- verify generated outputs;
- review git diff;
- commit the period and process changes together when appropriate.

---

## Canonical command order

    build taxonomy
        ↓
    final analysis
        ↓
    time-universe validation
        ↓
    EDA
        ↓
    taxonomy review
        ↓
    final analysis again if taxonomy changed
        ↓
    Standard Report
        ↓
    Period-Close Checklist
        ↓
    archive
        ↓
    historical integration
        ↓
    commit

---

## Non-negotiable rules

1. Do not manually edit final analytical CSVs.
2. Do not reduce Apple Screen Time for the Brother/Desktop correction.
3. Do not treat Off-Device Life as missing time.
4. Do not force analytical activity to equal clock capacity.
5. Do not change taxonomy merely because a node is large.
6. Do not diagnose burnout from a single period.
7. Do not discard unapplied adjustment time.
8. Do not make undocumented manual changes to a closed period.
9. Do not let the Standard Report become the EDA.
10. Do not rely on chat history to reproduce the pipeline.
