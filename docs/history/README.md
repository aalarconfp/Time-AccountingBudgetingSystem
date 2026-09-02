# docs/history

Retired files kept for reference only. **Nothing here is part of the active
pipeline.** The `.py.txt` extension is deliberate so these cannot be run or
imported by accident. Full development history is in git.

| File | Was | Retired | Replaced by |
|---|---|---|---|
| `period_process.py.txt` | Monolithic period orchestrator | 2026-09 restructuring | The explicit stage sequence in [`../SYSTEM_TRACKER_RUNBOOK.md`](../SYSTEM_TRACKER_RUNBOOK.md). It referenced a non-existent `period_close_validator_v5.py`, used the wrong iPhone screenshot path, skipped `daily_time_builder.py`, ran `integration_analysis.py` before the integrated build, auto-promoted iPhone extractions, and omitted `integration_human_review.py`. Do not revive it. |
| `integrated_daily_time_builder_backup.py.txt` | Ad-hoc backup of an earlier `integrated_daily_time_builder.py`, parked in the git-ignored `input/Integrated/` directory | 2026-09 restructuring | Current [`../../integrated_daily_time_builder.py`](../../integrated_daily_time_builder.py). Kept because this exact snapshot was never committed. |
| `PERIOD_PIPELINE_RUNBOOK_FINAL.md` | Second, competing operational runbook | 2026-09 doc consolidation | [`../SYSTEM_TRACKER_RUNBOOK.md`](../SYSTEM_TRACKER_RUNBOOK.md) (now the single canonical runbook) and [`../PROCESS_MAP.md`](../PROCESS_MAP.md) (dependency graph + machine map). It still referenced `period_close_validator_v5.py` and assumed a fixed 15-day period. |
| `README_ACTIVITYWATCH.md` | Early ActivityWatch integration notes | 2026-09 doc consolidation | [`../DATA_COLLECTION.md`](../DATA_COLLECTION.md) (completed-day rule, idempotency, Raw schema) and, for desktop machine facts, the Desktop Tracker Collector's `docs/DESKTOP_MACHINE.md`. Described a flat `output/Raw_ActivityWatch_*.csv` layout that no longer exists. |
| — `ACTIVITYWATCH_DESKTOP.md` (deleted, in git history) | Desktop machine facts | 2026-09 | Desktop Tracker Collector `docs/DESKTOP_MACHINE.md`. |

Other files removed in the same restructuring (recover from git history if ever
needed):

- `activitywatch_collector.py` — M0 read-only ActivityWatch collector (no CLI),
  superseded by `activitywatch_raw_loader.py`.
- `activitywatch_exporter.py` — earlier one-day ActivityWatch exporter,
  superseded by `activitywatch_raw_loader.py`. It produced a 14-column Raw
  schema (`Title`, `URL`, `AW_Category_Path`); the raw loader produces the
  current 12-column schema (`Window_Title`).
- `time_analysis.py` — M0 analysis over the legacy flat
  `output/Daily_Time/Daily_Time.csv`, superseded by `final_analysis.py`,
  `detail_analysis.py`, `exploratory_analysis.py`, `standard_report.py`.
- `test_aw_query.py` — one-off ActivityWatch query smoke test; re-homed in the
  Desktop Tracker Collector project as `diagnostics/aw_query_smoke.py`.
- `tracker_config.py` (repo root) — legacy config module. Its completed-day
  helpers (`today_local`, `latest_completed_date`, …) moved to
  `config/tracker_config.py`; everything else was already superseded by the
  `config/` package.
