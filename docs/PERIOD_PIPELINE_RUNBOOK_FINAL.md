System Tracker — Period Pipeline Runbook

Status: Canonical operational runbook
Baseline period: 2026-08-01 → 2026-08-15
Scope: Collection → source processing → integration → reconciliation → hierarchy → EDA → Standard Report → period close → historical integration

This document is the operational memory of the system. For a new period, follow the sequence below instead of reconstructing the process from chat history.

1. Operating model

The system has four source families:

ActivityWatch — ASUS laptop

ActivityWatch — desktop PC

Apple Screen Time — iPhone

Habit / Off-Device

The analytical accounting model is:

Clock Capacity
    =
Unique Tracked Time
    +
Off-Device Life

Unique Tracked Time
    =
Corrected Tracked Time
    -
Tracked Overlap

Analytical source totals can exceed clock capacity because multiple devices can observe the same elapsed time. This is not automatically an error.

Off-Device Life is intentional analytical time. It represents human-life maintenance and other activities that are not necessarily captured by device telemetry.

2. Before starting a new period

Set:

START_DATE = YYYY-MM-DD
END_DATE   = YYYY-MM-DD
MONTH      = YYYY-MM

Example:

START_DATE = 2026-08-01
END_DATE   = 2026-08-15
MONTH      = 2026-08

Activate the project environment:

.\.venv\Scripts\Activate.ps1

Verify Python:

python --version

Compile the core analytical scripts:

python -m py_compile ".\build_time_taxonomy.py"
python -m py_compile ".\fact_time_validator.py"
python -m py_compile ".\daily_time_builder.py"
python -m py_compile ".\integration_analysis.py"
python -m py_compile ".\integration_human_review.py"
python -m py_compile ".\integrated_daily_time_builder.py"
python -m py_compile ".\final_analysis.py"
python -m py_compile ".\detail_analysis.py"
python -m py_compile ".\exploratory_analysis.py"
python -m py_compile ".\standard_report.py"
python -m py_compile ".\period_close_validator_v5.py"

3. ActivityWatch — laptop

3.1 Machine

The laptop collector is:

activitywatch_laptop.py

It validates the expected laptop identity before collecting.

Run it on the laptop itself:

python ".\activitywatch_laptop.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

For a single completed day:

python ".\activitywatch_laptop.py" `
    --date "2026-08-15" `
    --force

3.2 Then run the ActivityWatch pipeline

The shared ActivityWatch pipeline is:

activitywatch_pipeline.py
    ↓
activitywatch_raw_loader.py
    ↓
fact_time_builder.py
    ↓
fact_time_validator.py

For explicit dates:

python ".\activitywatch_pipeline.py" `
    --date "2026-08-01" `
    --date "2026-08-02" `
    --date "2026-08-03"

For a whole completed month:

python ".\activitywatch_pipeline.py" `
    --month "2026-08"

Do not manually edit:

output\Raw\ActivityWatch\...
output\Fact_Time\...

If a source value is wrong, fix the source-processing or taxonomy logic rather than silently editing generated output.

4. ActivityWatch — desktop

Run the desktop collector on the desktop PC:

python ".\activitywatch_desktop.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

Single day:

python ".\activitywatch_desktop.py" `
    --date "2026-08-15" `
    --force

Then run:

python ".\activitywatch_pipeline.py" `
    --date "2026-08-01" `
    --date "2026-08-02"

or the relevant completed dates/month.

Desktop-specific rule

Desktop and laptop ActivityWatch data remain separately identifiable by device.

Do not merge the raw files manually.

The consolidation layer is responsible for combining the source datasets while preserving source/device identity.

5. iPhone Screen Time — evidence collection

The original screenshots are evidence.

Store them under:

input\
└── iPhone\
    └── ScreenTime\
        └── YYYY-MM\
            └── YYYY-MM-DD\
                ├── screenshot_01.png
                ├── screenshot_02.png
                └── ...

Example:

input\iPhone\ScreenTime\2026-08\2026-08-15\

Do not replace the original screenshots with processed files.

The canonical processed output is stored separately under:

output\Raw\AppleScreenTime\iPhone\YYYY-MM\YYYY-MM-DD\

6. iPhone Screen Time — processing

6.1 AI ingestion

Run:

python ".\iphone_screen_time_ingest.py" `
    --month "2026-08" `
    --date "2026-08-15"

For the full month:

python ".\iphone_screen_time_ingest.py" `
    --month "2026-08"

Use --dry-run when you only want screenshot coverage validation:

python ".\iphone_screen_time_ingest.py" `
    --month "2026-08" `
    --dry-run

6.2 Local rebuild

After taxonomy/logic changes that do not require new screenshots:

python ".\iphone_screen_time_rebuild.py" `
    --month "2026-08"

This is a zero-API-cost rebuild.

6.3 Manual evidence review

Before promotion:

Compare the candidate extraction with the original screenshot.

Check total Screen Time.

Check category totals.

Check unresolved/reconciliation residuals.

Confirm the date.

Do not promote a candidate that does not match the evidence.

6.4 Promote reviewed candidates

For reviewed dates:

python ".\iphone_screen_time_promote.py" `
    --month "2026-08" `
    --date "2026-08-15"

6.5 Resolve positive reconciliation residuals

The project includes a local unresolved-classification migration:

python ".\iphone_screen_time_categorize_unresolved.py" `
    --month "2026-08" `
    --date "2026-08-15"

Review the resulting classification before treating the residual as canonical.

6.6 Build iPhone source data

python ".\iphone_screen_time_builder.py" `
    --month "2026-08" `
    --date "2026-08-15" `
    --force

7. Habit / Off-Device — evidence collection

Store Habit screenshots under:

input\
└── Habit\
    └── YYYY-MM\
        └── YYYY-MM-DD\
            ├── screenshot_01.png
            ├── screenshot_02.png
            └── ...

Example:

input\Habit\2026-08\2026-08-15\

Habit is important because it captures legitimate human-life activity that devices cannot fully observe.

Examples include:

showering;

eating;

commuting;

active pauses;

small conversations;

offline work;

offline study;

other maintenance activities.

Do not treat this time as simply "missing telemetry."

8. Habit / Off-Device processing

8.1 AI ingestion

python ".\habit_offdevice_ingest.py" `
    --month "2026-08" `
    --date "2026-08-15"

Full month:

python ".\habit_offdevice_ingest.py" `
    --month "2026-08"

Dry validation:

python ".\habit_offdevice_ingest.py" `
    --month "2026-08" `
    --dry-run

8.2 Build canonical Habit time

python ".\habit_offdevice_builder.py" `
    --month "2026-08" `
    --date "2026-08-15" `
    --force

9. Taxonomy

The canonical taxonomy builder is:

build_time_taxonomy.py

Run:

python ".\build_time_taxonomy.py"

Expected result:

TIME TAXONOMY VALIDATION PASSED

Important taxonomy files:

output\Reference\Taxonomy\Dim_Activity.csv
output\Reference\Taxonomy\Dim_Category_Default.csv
output\Reference\Taxonomy\Dim_Domain.csv
output\Reference\Taxonomy\Dim_Energy.csv
output\Reference\Taxonomy\Dim_Goal.csv
output\Reference\Taxonomy\Taxonomy_Mapping_Review.csv

Taxonomy changes belong in the reference layer.

Do not manually patch final analysis CSVs to change analytical meaning.

10. Source validation

Validate Fact_Time:

python ".\fact_time_validator.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15"

Build source Daily_Time:

python ".\daily_time_builder.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --source asus_laptop

Repeat with the appropriate configured source:

asus_laptop
desktop
iphone
habit

Do not assume a source is complete merely because one CSV exists. Validate date coverage.

11. Preliminary integration

Run:

python ".\integration_analysis.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --unaccounted-target-hours 3

This is a diagnostic/preliminary integration analysis.

Then generate the Habit human-review template:

python ".\integration_human_review.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15"

The main editable Habit adjustment file is:

input\Integrated\Habit_Manual_Adjustments.csv

12. Manual integration review

This is a controlled human checkpoint.

Review:

input\Integrated\Habit_Manual_Adjustments.csv
input\Integrated\Manual_Adjustments.csv
input\Integrated\Classification_Weights.csv

Review the integration-generated human-review outputs under:

output\Integrated\Analysis\Human_Review\

Manual adjustment rules

Every adjustment must have a reason.

Do not:

delete records silently;

edit generated final CSVs;

use a manual adjustment to conceal a source-processing bug;

reduce one device merely because another device appears to contain the same time.

The correction layer must preserve the audit trail.

13. Apply Habit/manual adjustments

The adjustment processor is:

habit_manual_adjustments.py

Run:

python ".\habit_manual_adjustments.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --adjustment-file ".\input\Integrated\Habit_Manual_Adjustments.csv" `
    --force

Review the generated audit before proceeding.

14. Build Integrated Daily Time

The canonical integration builder is:

integrated_daily_time_builder.py

Run:

python ".\integrated_daily_time_builder.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --manual-input ".\input\Integrated\Manual_Adjustments.csv" `
    --classification-input ".\input\Integrated\Classification_Weights.csv"

This is the point where the source-specific datasets become the integrated daily analytical input.

15. Final reconciliation

Run:

python ".\final_analysis.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

Expected final directory:

output\Integrated\Analysis\Final\2026-08-01_2026-08-15\

Expected major outputs include:

Final_Analysis_*.csv
Final_Analysis_By_Device_Category_Subcategory_Domain_Energy_Goal_*.csv
Final_Source_Reconciliation_*.csv
Final_Daily_Reconciliation_*.csv
Final_Correction_Audit_*.csv
Final_Attribution_Removals_*.csv
Final_Time_Universe_Reconciliation_*.csv
Final_Analysis_Report_*.txt

16. Final reconciliation review

Review:

Final_Correction_Audit_*.csv
Final_Attribution_Removals_*.csv
Final_Source_Reconciliation_*.csv
Final_Daily_Reconciliation_*.csv
Final_Time_Universe_Reconciliation_*.csv

Pay special attention to:

REVIEW days;

unapplied corrections;

attribution removals;

classification removals;

overlap;

uncovered time;

Off-Device Life;

unexpected source/device totals.

A review flag is not automatically an error.

It means the analyst must understand the condition before closing the period.

17. Time-universe accounting

For the period:

Clock Capacity
=
Calendar Days × 24 × 60

Then:

Unique Tracked
=
Corrected Tracked
-
Tracked Overlap

And:

Analytical Total
=
Unique Tracked
+
Off-Device Life

The analytical total should reconcile to clock capacity.

Example baseline:

Capacity          360h 00m
Corrected tracked 340h 40m
Overlap             4h 53m
Unique tracked    335h 47m
Off-device life    24h 12m
Analytical total  360h 00m

18. Detailed hierarchy analysis

Once final reconciliation is frozen:

python ".\detail_analysis.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

The hierarchy should be reviewed across:

Device
Device → Category
Device → Category → Subcategory
Device → Category → Subcategory → Domain
Device → Category → Subcategory → Domain → Energy
Device → Category → Subcategory → Domain → Energy → Goal

Category
Category → Subcategory
Category → Subcategory → Domain
Category → Subcategory → Domain → Energy
Category → Subcategory → Domain → Energy → Goal

Domain
Energy
Goal

Off-Device Life should have meaningful analytical dimensions at the deepest level.

19. Exploratory Data Analysis

Run:

python ".\exploratory_analysis.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

EDA is diagnostic.

Use it to investigate:

large contributors;

concentration;

unusual categories;

Uncategorized records;

generic buckets;

taxonomy candidates;

domain/energy/goal distributions;

possible behavioral patterns.

Do not automatically change taxonomy because EDA identifies a large node.

A large node can be a genuine behavior.

20. Taxonomy review loop

If EDA suggests that a mapping is genuinely wrong:

EDA finding
    ↓
Human review
    ↓
Reference taxonomy change
    ↓
build_time_taxonomy.py
    ↓
final_analysis.py
    ↓
detail_analysis.py
    ↓
exploratory_analysis.py
    ↓
standard_report.py
    ↓
period-close validation

Do not change only the generated CSV.

The taxonomy reference is the source of analytical meaning.

21. Standard Report

Run:

python ".\standard_report.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --force

The Standard Report is intentionally much simpler than EDA.

It should focus on stable KPIs and concise recommendations.

The EDA is where detailed exploratory questions belong.

22. Period-close validation

The final validator is:

period_close_validator_v5.py

Run:

python ".\period_close_validator_v5.py" `
    --start-date "2026-08-01" `
    --end-date "2026-08-15" `
    --require-eda `
    --require-standard-report

A successful result must end with:

RESULT: PERIOD CLOSE VALIDATION PASSED.

The validator checks accounting and structural integrity.

It intentionally does not require EDA text markers such as:

Flags : N
Taxonomy candidates : N

EDA is exploratory and may evolve its report structure.

23. Period-close decision

Only close when:

Period valid
Source coverage understood
Taxonomy validated
Final analysis generated
Correction audit reviewed
Daily reconciliation reviewed
Time universe reconciled
Hierarchy generated
EDA reviewed
Standard Report generated
Period-close validator PASSED

The close states are:

CLOSED
CLOSED WITH DOCUMENTED REVIEW ITEMS
NOT CLOSED

24. Historical integration

Historical integration is deliberately separate from period reconciliation.

The existing project documentation identifies historical integration as a controlled process covering approximately one year of prior data.

Use:

docs/HISTORICAL_DATA_INTEGRATION.md

Do not mix historical integration logic into:

final_analysis.py

Historical integration should happen after the current period is internally closed.

25. Budget

Budgeting is not part of the current period-close accounting engine.

The future budget layer should be constructed from current goals and should remain separate from historical factual time.

Use:

docs/BUDGET_DESIGN.md

when the budget layer is introduced.

26. Archive

For every closed period preserve:

Raw/source evidence
Source-specific processed data
Integrated daily data
Manual review CSVs
Correction audits
Final analysis
Hierarchy
Time-universe reconciliation
EDA
Standard Report
Period-close validation result
Taxonomy state/version
Period notes

Do not overwrite a closed period without recording the reason.

27. Git commit procedure

Before committing:

git status

Review changes:

git diff --stat
git diff

Verify that generated/private data is not accidentally being committed.

Check:

git status --short

Add only intended code/documentation changes.

Example:

git add `
    docs `
    *.py `
    *.ps1

Then inspect the staged set:

git diff --cached --stat
git diff --cached

Commit:

git commit -m "Document period analysis pipeline and close process"

Verify:

git status
git log -1 --oneline

If the working tree contains generated period data that should not be committed, do not use git add . blindly.

28. Next-period quick-start checklist

For the next 15-day period:

[ ] Define START_DATE / END_DATE
[ ] Activate .venv

LAPTOP
[ ] Collect ActivityWatch
[ ] Run ActivityWatch pipeline

DESKTOP
[ ] Collect ActivityWatch
[ ] Run ActivityWatch pipeline

IPHONE
[ ] Save screenshots
[ ] Run iphone_screen_time_ingest.py
[ ] Review candidates against screenshots
[ ] Promote reviewed candidates
[ ] Resolve legitimate residuals
[ ] Build iPhone source data

HABIT
[ ] Save screenshots
[ ] Run habit_offdevice_ingest.py
[ ] Review extraction
[ ] Build Habit source data

SOURCES
[ ] Run taxonomy validation
[ ] Validate Fact_Time
[ ] Build Daily_Time
[ ] Check coverage

INTEGRATION
[ ] Run integration_analysis.py
[ ] Generate human-review template
[ ] Review/edit manual CSVs
[ ] Apply Habit/manual adjustments
[ ] Build Integrated Daily Time

FINAL
[ ] final_analysis.py
[ ] Review correction audit
[ ] Review daily reconciliation
[ ] Review time universe
[ ] detail_analysis.py
[ ] exploratory_analysis.py
[ ] Review taxonomy candidates
[ ] Apply intentional taxonomy changes only
[ ] Re-run affected analysis if taxonomy changed
[ ] standard_report.py
[ ] period_close_validator_v5.py

CLOSE
[ ] Period-Close Checklist
[ ] Archive
[ ] Historical integration or explicit deferral
[ ] Git diff
[ ] Git commit

29. Operational principles

Raw evidence is preserved.

Source processors own source normalization.

Integration owns cross-source consolidation.

Taxonomy owns analytical meaning.

Final analysis owns reconciliation.

Time-universe accounting owns elapsed-time reconciliation.

EDA owns exploration, not automatic taxonomy changes.

Standard Report owns recurring KPIs and concise recommendations.

Period-close validation owns structural/accounting validation.

Historical integration remains a separate layer.

Budgeting remains a future planning layer.

Manual interventions must remain auditable.

Generated outputs should not be manually patched.

A review flag must be understood before close.

A closed period must be reproducible from this runbook.

30. Canonical dependency graph

ActivityWatch Laptop ─┐
                      ├─> Fact_Time ─> Daily_Time ─┐
ActivityWatch Desktop ┘                            │
                                                   │
iPhone screenshots ─> iPhone extraction ─> Daily ─┤
                                                   ├─> Integration
Habit screenshots ──> Habit extraction ──> Daily ─┘
                                                   │
Taxonomy reference ───────────────────────────────┤
                                                   ▼
                                      Final Reconciliation
                                                   │
                           ┌───────────────────────┼───────────────────────┐
                           ▼                       ▼                       ▼
                       Hierarchy                EDA                Standard Report
                           │                       │                       │
                           └───────────────────────┴───────────────────────┘
                                                   │
                                                   ▼
                                      Period-Close Validator
                                                   │
                                                   ▼
                                      Archive / Historical
                                                   │
                                                   ▼
                                                Commit

31. Files that define the process

Primary operational scripts:

activitywatch_laptop.py
activitywatch_desktop.py
activitywatch_pipeline.py
activitywatch_raw_loader.py
fact_time_builder.py
fact_time_validator.py
daily_time_builder.py

iphone_screen_time_ingest.py
iphone_screen_time_rebuild.py
iphone_screen_time_promote.py
iphone_screen_time_categorize_unresolved.py
iphone_screen_time_builder.py

habit_offdevice_ingest.py
habit_offdevice_builder.py

build_time_taxonomy.py
integration_analysis.py
integration_human_review.py
habit_manual_adjustments.py
integrated_daily_time_builder.py

final_analysis.py
detail_analysis.py
exploratory_analysis.py
standard_report.py
period_close_validator_v5.py

Primary documentation:

docs/ACTIVITYWATCH_LAPTOP.md
docs/ACTIVITYWATCH_DESKTOP.md
docs/DATA_COLLECTION.md
docs/SOURCE_PROCESSING.md
docs/INTEGRATION_AND_RECONCILIATION.md
docs/TAXONOMY_AND_EDA.md
docs/REPORTING.md
docs/PERIOD_CLOSE_CHECKLIST.md
docs/HISTORICAL_DATA_INTEGRATION.md
docs/BUDGET_DESIGN.md
docs/TROUBLESHOOTING.md
docs/CHANGE_CONTROL.md
docs/GLOSSARY.md

This file is the cross-source operational index connecting those documents to the executable pipeline.