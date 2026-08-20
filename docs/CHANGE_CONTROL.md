# Change Control

## Purpose

Prevent analytical drift between reporting periods.

## Change classes

### Class A — Data correction

Example:

- missing source file;
- wrong export;
- duplicated input.

Requires rerun and audit.

### Class B — Taxonomy correction

Example:

- ActivityWatch System Processes mapped incorrectly.

Requires:

- taxonomy change;
- taxonomy rebuild;
- validation;
- final rerun;
- EDA rerun;
- Standard Report rerun.

### Class C — Analytical logic change

Example:

- changing overlap treatment;
- changing Off-Device Life calculation;
- changing KPI definitions.

Requires:

- explicit documentation;
- before/after comparison;
- impact assessment;
- test run;
- commit.

### Class D — New feature

Example:

- budget;
- historical automation;
- trend dashboard.

Keep separate from routine period processing until stable.

## Freeze rule

Once a period has passed the Period-Close Checklist, do not change its
analytical interpretation without recording a versioned correction.
