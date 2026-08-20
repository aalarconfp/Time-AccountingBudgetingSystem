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
