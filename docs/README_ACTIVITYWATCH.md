# ActivityWatch Integration

## Purpose

ActivityWatch is the computer-activity source for the new System Tracker.

The ActivityWatch integration is intentionally separated into two layers:

1. **Raw ActivityWatch** — faithful copy of canonical ActivityWatch events.
2. **Fact_Time** — future analytical layer that transforms raw activity into tracker-ready time facts.

The raw layer must remain auditable and should not be modified to match historical tracker data.

---

## System Architecture

```text
ActivityWatch
     │
     ▼
Canonical ActivityWatch Query
     │
     ▼
activitywatch_raw_loader.py
     │
     ▼
Raw_ActivityWatch
     │
     ▼
Future Fact_Time transformation
     │
     ▼
Daily / Weekly / Monthly tracker
```

---

## Cutover Date

The new tracker officially begins:

**2026-08-01**

ActivityWatch data before August 1 is intentionally outside the initial scope of the new tracker.

Historical ActivityWatch data from April–July remains available for a future reconciliation project comparing the old tracker against the new tracker.

Do not modify historical raw ActivityWatch data for that purpose.

---

## Completed-Day Rule

The tracker analyzes only **completed local calendar days** by default.

The current day is considered incomplete and is excluded from normal analysis.

For example, on August 10:

```text
Included:
2026-08-01
2026-08-02
...
2026-08-09

Excluded:
2026-08-10
```

This prevents partial-day data from being interpreted as a complete day's activity.

The rule applies automatically based on the computer's local timezone.

---

## Current-Day Exception

Today's data can be deliberately collected with:

```powershell
python activitywatch_raw_loader.py --include-today
```

This should only be used when there is a specific reason to inspect incomplete current-day activity.

Normal daily operation should not use this option.

---

## Daily Workflow

The normal command is:

```powershell
python activitywatch_raw_loader.py
```

This means:

> Load yesterday, the most recent completed calendar day.

Example:

If today is August 10:

```text
Command:
python activitywatch_raw_loader.py

Loads:
2026-08-09
```

The following day, August 11:

```text
Command:
python activitywatch_raw_loader.py

Loads:
2026-08-10
```

No date needs to be manually changed.

---

## Common Commands

### Load yesterday

```powershell
python activitywatch_raw_loader.py
```

### Load a specific completed date

```powershell
python activitywatch_raw_loader.py --date 2026-08-09
```

### Load the previous 7 completed days

```powershell
python activitywatch_raw_loader.py --days 7
```

### Load a historical range

```powershell
python activitywatch_raw_loader.py --start-date 2026-08-01 --end-date 2026-08-09
```

### Explicitly include today

```powershell
python activitywatch_raw_loader.py --include-today
```

### Explicitly include today's date

```powershell
python activitywatch_raw_loader.py --date 2026-08-10 --include-today
```

### Check the generated files

```powershell
Get-ChildItem ".\output" -Filter "Raw_ActivityWatch_*.csv"
```

### Inspect the first rows

```powershell
Get-Content ".\output\Raw_ActivityWatch_2026-08-09.csv" -TotalCount 11
```

### Count rows

```powershell
(Get-Content ".\output\Raw_ActivityWatch_2026-08-09.csv").Count
```

The count includes the CSV header.

---

## Python Environment

Confirm which Python is being used:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

Expected environment currently:

```text
C:\ProgramData\anaconda3\python.exe
```

Confirm ActivityWatch client installation:

```powershell
python -c "import aw_client; print('aw-client import OK')"
```

---

## ActivityWatch Server

ActivityWatch normally runs locally at:

```text
http://localhost:5600
```

The raw loader connects to this local server.

The loader is **READ ONLY** with respect to ActivityWatch. It does not insert, modify, or delete ActivityWatch events.

---

## Raw Dataset Location

Raw files are stored under:

```text
_Tracker/
└── output/
    └── Raw_ActivityWatch_YYYY-MM-DD.csv
```

Example:

```text
output/
├── Raw_ActivityWatch_2026-08-01.csv
├── Raw_ActivityWatch_2026-08-03.csv
├── Raw_ActivityWatch_2026-08-04.csv
├── Raw_ActivityWatch_2026-08-05.csv
├── Raw_ActivityWatch_2026-08-06.csv
├── Raw_ActivityWatch_2026-08-07.csv
└── Raw_ActivityWatch_2026-08-10.csv
```

Dates with no ActivityWatch data do not need a CSV file.

---

## Raw Dataset Schema

Each raw event contains:

```text
Date
Start
End
Duration_sec
Device
Source
Bucket
AW_Event_ID
App
Window_Title
AW_Category
AW_Subcategory
```

### AW_Event_ID

`AW_Event_ID` is the natural key used for duplicate protection.

Running the loader multiple times must not create duplicate raw events.

---

## Idempotency

The loader is designed to be safely rerunnable.

Example:

```text
First run:
ActivityWatch events : 400
New events added     : 400

Second run:
ActivityWatch events : 400
New events added     : 0
Already in CSV       : 400
```

If ActivityWatch records additional events after the first run:

```text
First run:
Existing : 400
New      : 10
Final    : 410

Later run:
Existing : 410
New      : 5
Final    : 415
```

Only previously unseen `AW_Event_ID`s are added.

---

## Duplicate Handling

ActivityWatch canonical queries can occasionally return duplicate event IDs.

The loader reports:

```text
ActivityWatch events
Unique ActivityWatch IDs
Duplicate retrieved events
Already in CSV
New events added
Final CSV rows
```

Duplicate IDs returned within one ActivityWatch retrieval are discarded.

Existing IDs already present in the CSV are not inserted again.

---

## Empty Days

If ActivityWatch returns zero events for a date:

```text
No ActivityWatch data for this date.
```

The loader does not create an empty CSV.

This avoids confusing:

> No data collected

with:

> Data was collected and contained zero activity.

---

## Recommended Daily Routine

At the beginning of a new analysis session:

```powershell
cd "G:\My Drive\Personal Life\Habit and Wellness\System\_Tracker"
python activitywatch_raw_loader.py
```

This loads the previous completed day.

Then verify:

```powershell
Get-ChildItem ".\output" -Filter "Raw_ActivityWatch_*.csv" | Sort-Object Name
```

If necessary, inspect the latest file:

```powershell
Get-Content ".\output\Raw_ActivityWatch_2026-08-09.csv" -TotalCount 11
```

---

## Backfill

For the initial new-system historical period:

```powershell
python activitywatch_raw_loader.py --start-date 2026-08-01 --end-date 2026-08-09
```

For a rolling historical refresh:

```powershell
python activitywatch_raw_loader.py --days 7
```

The loader is idempotent, so backfills can safely overlap existing dates.

---

## Current Development Status

### Completed

* ActivityWatch server connection
* ActivityWatch bucket discovery
* Canonical ActivityWatch query
* AFK filtering
* Category mapping
* Raw CSV export
* Duplicate protection
* Incremental loading
* Multi-day loading
* Historical backfill
* Completed-day rule

### Current Cutover

```text
2026-08-01
```

### Next Layer

```text
Raw_ActivityWatch
        ↓
Fact_Time
```

`Fact_Time` will be the analytical time-fact layer used by the broader tracker.

---

## Future Reconciliation Project

ActivityWatch contains historical data from before the new tracker cutover.

The old tracker and new tracker should eventually be compared to understand:

* differences in definitions;
* differences in categorization;
* missing days;
* manual vs. automatically captured time;
* changes in measurement methodology;
* historical continuity.

That reconciliation is deliberately deferred.

The raw ActivityWatch data must remain unchanged so it can serve as the source of truth for that future analysis.
