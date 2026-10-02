# old scripts — superseded, kept for reference only

These files are archived unchanged. Do not run them for new periods.

| File | Was | Superseded by |
|---|---|---|
| `habit_offdevice_ingest.py` | AI ingestion of Habit screenshots under `input/Habit/<YYYY-MM>/<YYYY-MM-DD>/` reading cumulative tracker state | `habit_screenshot_ingest.py` (evidence index + manifest + bar charts) |
| `habit_offdevice_builder.py` | Habit Daily_Time from weekly/monthly cumulative deltas, Monday/first-of-month resets and `input/Integrated/Habit_Initial_Baselines.csv` | `habit_screenshot_builder.py` (direct daily evidence; no deltas, resets or baselines) |
| `validate_habit_baselines.ps1` | Validated `Habit_Initial_Baselines.csv` for the cumulative builder | Not needed: the new pipeline has no baselines |

August 2026 Habit outputs were produced by these scripts and are left as they are.
`habit_manual_adjustments.py` is **not** part of this archive; it remains the
active post-analysis adjustment step.
