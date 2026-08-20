# System Tracker — August 2026 Audit

## Scope

Baseline requested: 2026-08-01 through 2026-08-15.

Configured source streams:
1. ActivityWatch — AsusLaptop-Andres
2. ActivityWatch — DesktopPC-Andres
3. Apple Screen Time — iPhone
4. Habit / OffDevice

## Current status from the supplied project ZIP

### Habit / OffDevice

- Input screenshots: 15/15 dates
- Raw AI extractions: 15/15 dates
- Fact outputs: 15/15 dates
- Daily outputs: 15/15 dates
- Standard categories in the builder: 13
- Overlap: allowed
- 24-hour reconciliation: disabled
- Current observed/fact totals are therefore intentionally allowed to exceed 24 hours.

Status: READY FOR TAXONOMY INTEGRATION.

### iPhone Screen Time

- Input screenshots: 15/15 dates
- Canonical AI extractions: 15/15 dates
- Fact outputs: 15/15 dates
- Daily outputs: 15/15 dates
- The August 11 anomaly is preserved as a reconciliation anomaly rather than creating artificial time.
- `Other` appears in the iPhone facts and is not part of the 12-category canonical taxonomy.

Status: READY FOR TAXONOMY INTEGRATION, with an explicit `Apple Other` fallback mapping required.

### ActivityWatch — AsusLaptop-Andres

Raw/Fact coverage in the supplied ZIP:
- 2026-08-01 through 2026-08-10
- 2026-08-13

Missing from the requested baseline:
- 2026-08-11
- 2026-08-12
- 2026-08-14
- 2026-08-15

Fact coverage matches the raw coverage.

Daily_Time coverage is materially incomplete:
- 2026-08-10
- 2026-08-13

The supplied project therefore does NOT currently have a complete Asus ActivityWatch Daily_Time baseline.

### ActivityWatch — DesktopPC-Andres

Raw/Fact coverage:
- 2026-08-01 through 2026-08-05
- 2026-08-07 through 2026-08-13

Missing:
- 2026-08-06
- 2026-08-14
- 2026-08-15

Daily_Time coverage exists for the dates for which raw/fact data exists, but the overall 1–15 baseline remains incomplete.

## Important architectural findings

### 1. There are currently two competing Fact/Daily architectures

Legacy:
- `output/Fact_Time/`
- `output/Daily_Time/`

New:
- `output/Fact/Time/<source>/<device>/`
- `output/Daily/Time/<source>/<device>/`

The legacy directories contain historical August files and should NOT be deleted yet. They should be explicitly marked legacy and frozen while the new architecture is validated.

### 2. ActivityWatch is not yet fully integrated

`fact_time_builder.py` supports the configured ActivityWatch devices, but the supplied ActivityWatch pipeline is still effectively a single-date/single-source orchestration.

`daily_time_builder.py` is source-aware, but the supplied ZIP does not contain complete Daily_Time outputs for both devices.

### 3. Integrated Daily Time currently only selects ActivityWatch device sources

The current integrated builder defaults to the two ActivityWatch device sources.

It does not yet include:
- iPhone
- Habit / OffDevice

This is the biggest integration gap.

### 4. Current Integrated Daily Time still assumes 24-hour residual logic

The existing residual calculation subtracts observed and manual time from 24 hours.

That logic is not valid after combining:
- iPhone time
- ActivityWatch time
- Habit / OffDevice time

because those observations can overlap.

The final integrated layer should therefore preserve observed activity time without forcing a 24-hour reconciliation. A separate elapsed-time/overlap analysis should handle the 24-hour question.

### 5. Taxonomy is currently duplicated

There is an existing Python taxonomy in `config/taxonomy.py`.

There is also a new `build_time_taxonomy.py`, but the supplied ZIP does not contain the corresponding `Dim_*.csv` taxonomy files.

The final design should have one authoritative taxonomy source and have all four source builders consume it.

### 6. Habit ingestion and Habit builder taxonomy lists differ

The ingestion script currently has 12 standard categories.

The builder currently has 13 and includes:
- Motorcycle Time
- Console Time Tracking

The builder's 13-category list is the correct current standard based on the supplied August data. The ingestion prompt/normalization layer should be updated to use the same 13-category definition.

### 7. ActivityWatch contains a substantial Uncategorized pool

Observed raw ActivityWatch data contains:
- Productivity & Finance
- Education
- Utilities
- Entertainment
- Information & Reading
- Social Networking
- Games
- Creativity
- Shopping & Food
- Health & Fitness
- Uncategorized

`Uncategorized` is not a canonical analytical category.

It should remain visible as an unmapped quality bucket until manually/classification-weight mapped. It should not silently receive Domain/Energy/Goal values.

### 8. iPhone contains one noncanonical source category

`Other` occurs repeatedly in the iPhone facts.

Recommended handling:
- Preserve the source value as `Source_Category = Other`
- Map the canonical analytical category to `Utilities`
- Mark the mapping as `Fallback`
- Preserve a review flag so the final analysis can quantify Apple Other separately.

## Recommended final architecture

INPUT
→ source-specific RAW/CANONICAL extraction
→ source-specific FACT
→ source-specific DAILY
→ centralized taxonomy mapping
→ Integrated Activity Dataset
→ final analysis

The integrated dataset should contain:

- Date
- Source
- Device
- Source_Category
- Source_Subcategory
- Category
- Subcategory
- Domain
- Energy
- Goal
- Duration_sec
- Event_Count
- Allocation_Type
- Evidence_Type
- Evidence_Source
- Mapping_Type
- Mapping_Status

## Final analysis should report two different concepts

### Activity time

The amount of time reported by each tracker.

This may legitimately exceed 24 hours when activities overlap.

### Elapsed/clock time

Actual time available in the day.

This should be analyzed separately and should not be calculated by blindly summing all four trackers.

## Required implementation sequence

1. Backfill/verify ActivityWatch raw data for Aug 1–15.
2. Build ActivityWatch Fact_Time for both devices.
3. Build ActivityWatch Daily_Time for both devices.
4. Replace duplicated taxonomy definitions with one authoritative taxonomy layer.
5. Integrate Category / Domain / Energy / Goal into all four source pipelines.
6. Preserve source-specific evidence and mapping status.
7. Generalize Integrated Daily Time to all four source streams.
8. Disable automatic 24-hour residual calculation for the multi-source activity dataset.
9. Keep Uncategorized and Apple Other explicitly visible as quality/review buckets.
10. Build the final Category / Domain / Energy / Goal analysis for Aug 1–15.
11. Create permanent project documentation and an August baseline report.
12. Only after validation, archive/freeze the legacy `output/Fact_Time` and `output/Daily_Time` directories.

## Conclusion

The iPhone and Habit pipelines are substantially complete for Aug 1–15.

The project is NOT yet ready for final integrated analysis because ActivityWatch coverage/Daily_Time coverage is incomplete and the current Integrated Daily Time builder does not consume iPhone or Habit data.

The next implementation should therefore be an integration/refactor pass, not another independent tracker pipeline.
