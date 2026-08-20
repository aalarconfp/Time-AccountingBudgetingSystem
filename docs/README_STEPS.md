# Habit & Wellness System Tracker

This repository contains the operational pipeline for collecting, integrating,
reconciling, analyzing, and reporting personal time data.

## Canonical workflow

1. Prepare reporting period
2. Prepare Python environment
3. Collect ActivityWatch laptop data
4. Collect ActivityWatch desktop data
5. Collect Apple Screen Time data
6. Collect Habit / Off-Device data
7. Validate source coverage
8. Run source-specific processors
9. Integrate daily source data
10. Review raw integration
11. Review and enter period adjustments
12. Build and validate taxonomy
13. Run final reconciliation
14. Review correction audit
15. Review daily reconciliation
16. Validate the time universe
17. Validate the analytical hierarchy
18. Run exploratory analysis
19. Review taxonomy candidates
20. Apply only intentional taxonomy changes
21. Re-run affected analysis
22. Run the Standard Report
23. Execute the Period-Close Checklist
24. Archive the period
25. Integrate with historical data
26. Commit and document the period

## Accounting model

The elapsed-time universe is the source of truth:

    Clock Capacity = Unique Tracked Time + Off-Device Life

and:

    Unique Tracked Time = Corrected Tracked Time - Tracked Overlap

Analytical activity can exceed clock capacity because multiple sources can
observe the same elapsed time.

## Documentation

- `docs/SYSTEM_TRACKER_RUNBOOK.md` — complete operating procedure.
- `docs/PERIOD_CLOSE_CHECKLIST.md` — mandatory period-close checklist.
- `docs/PROCESS_MAP.md` — pipeline architecture and dependencies.
- `docs/DATA_COLLECTION.md` — source collection procedure.
- `docs/SOURCE_PROCESSING.md` — source-specific processing.
- `docs/INTEGRATION_AND_RECONCILIATION.md` — consolidation and adjustment rules.
- `docs/TAXONOMY_AND_EDA.md` — taxonomy, hierarchy, and EDA.
- `docs/REPORTING.md` — Standard Report and recurring KPI definitions.
- `docs/HISTORICAL_DATA_INTEGRATION.md` — one-year historical integration procedure.
- `docs/BUDGET_DESIGN.md` — future budget design based on current goals.
- `docs/TROUBLESHOOTING.md` — common failures and recovery.
- `docs/CHANGE_CONTROL.md` — rules for changing the analytical system.
- `docs/GLOSSARY.md` — canonical terminology.

Existing source-specific documentation should remain alongside these documents.
