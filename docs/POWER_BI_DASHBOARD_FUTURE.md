# Power BI Dashboard — Future Implementation Idea

**Status:** Future enhancement  
**Scope:** System Tracker analytical reporting  
**Recommended timing:** After 2–4 comparable analysis periods have accumulated

## 1. Objective

Create a Power BI dashboard that turns the System Tracker's validated CSV outputs into a longitudinal view of time allocation, life domains, energy, goals, off-device life, and data quality.

The dashboard should complement—not replace—the existing `.txt` reports.

- **CSV outputs:** machine-readable analytical source.
- **TXT reports:** human-readable period reports.
- **Power BI:** interactive historical analysis and KPI visualization.

## 2. Recommended Architecture

```text
Device collection
      ↓
Source processing
      ↓
Consolidation
      ↓
Manual review
      ↓
Final analysis
      ↓
Power BI export layer
      ↓
Power BI
```

Eventually add:

```text
powerbi_export.py
```

Its purpose would be to normalize validated period outputs into stable Power BI-ready datasets.

Recommended datasets:

```text
output/PowerBI/
    FactTime.csv
    FactDaily.csv
    FactPeriod.csv
```

The archived period folders should remain unchanged for reproducibility.

## 3. Data Model

Use a **star schema**.

### FactTime

Core analytical fields:

- Date
- Period_ID
- Period_Start
- Period_End
- Device
- Category
- Subcategory
- Domain
- Energy
- Goal
- Duration_sec
- Duration_min

### Dimensions

- DimDate
- DimPeriod
- DimDevice
- DimCategory
- DimSubcategory
- DimDomain
- DimEnergy
- DimGoal

The existing taxonomy should remain the source of truth for these dimensions.

## 4. Dashboard Pages

### 4.1 Executive Overview

Stable, simple KPIs:

- Capacity
- Unique tracked time
- Off-device life
- Tracked overlap
- Largest categories
- Maintenance / Investment / Consumption
- Recovery / Deep / Active / Shallow / Passive

The goal is to answer:

> What happened during this period?

### 4.2 Time Allocation

Explore:

```text
Device
  → Category
    → Subcategory
```

Useful views:

- hours by category
- percentage of capacity
- device contribution
- period-over-period change

### 4.3 Life Balance

Explore:

```text
Domain
  → Energy
    → Goal
```

Primary dimensions:

- Physical
- Vocational
- Relational
- Recreational
- Intellectual
- Economical
- Spiritual

Energy:

- Recovery
- Deep
- Active
- Shallow
- Passive

Goals:

- Maintenance
- Investment
- Consumption

### 4.4 Exploratory Analysis

Expose diagnostic information from the EDA layer:

- large analytical nodes
- uncategorized activity
- taxonomy candidates
- unusual changes
- device/category anomalies
- domain/energy/goal shifts

This remains separate from the simple recurring KPI report.

### 4.5 Historical Trends

Once multiple periods exist:

- current vs previous period
- change in hours
- change in percentage
- historical average
- rolling baseline
- category trends
- domain trends
- energy trends
- off-device-life trends

### 4.6 Data Quality

Optional but recommended:

- reconciliation status
- overlap
- review flags
- source coverage
- period validation
- correction activity

A dashboard should never hide data-quality problems behind attractive charts.

## 5. Off-Device Life

Off-device life should be treated as a **real component of human time**, not simply missing data.

Current model:

```text
Off-Device Life
    → Untracked Maintenance
        → Physical
            → Active
                → Maintenance
```

As manual/off-device tracking becomes more detailed, this could eventually become:

```text
Eating
Shower / hygiene
Commuting
Active pauses
Small conversations
Household maintenance
Other life maintenance
```

A future dashboard should monitor this against the user's own historical baseline.

A sustained reduction could become an exploratory signal for possible overload or burnout, but should **not** be interpreted as proof of burnout by itself.

## 6. Why Wait for 2–4 Periods?

The first period establishes the pipeline.

Several comparable periods establish a baseline.

That allows Power BI to answer:

> Is this period unusual relative to the person's own history?

rather than relying on arbitrary external thresholds.

The August 1–15 period should therefore remain the **reference period** for the initial dashboard design.

## 7. Design Principle

Keep the reporting layers separate:

```text
Standard Report
    ↓
"What happened?"

EDA
    ↓
"Where should I investigate?"

Power BI
    ↓
"How does this compare with my history?"
```

Power BI should not become another complicated analytical engine. The existing Python pipeline remains responsible for collection, reconciliation, taxonomy, corrections, and analytical calculations.

## 8. Future Implementation Sequence

When enough historical periods exist:

1. Review stable fields across periods.
2. Define the Power BI data contract.
3. Build `powerbi_export.py`.
4. Generate normalized historical CSVs.
5. Validate totals against Final Analysis.
6. Build the star-schema Power BI model.
7. Create the Executive Overview.
8. Add Time Allocation.
9. Add Life Balance.
10. Add EDA diagnostics.
11. Add Historical Trends.
12. Add Data Quality.
13. Validate Power BI totals against the Python reports.
14. Document the Power BI refresh procedure.

**Principle:** Power BI is a visualization and longitudinal-analysis layer on top of the validated System Tracker pipeline—not a replacement for it.
