# Process Map

## High-level architecture

```text
Raw Sources
   │
   ├── ActivityWatch Laptop
   ├── ActivityWatch Desktop
   ├── Apple Screen Time
   └── Habit / Off-Device
          │
          ▼
Source-specific processors
          │
          ▼
Integrated daily records
          │
          ▼
Taxonomy / reference dimensions
          │
          ▼
Final reconciliation
          │
          ├── Correction Audit
          ├── Daily Reconciliation
          ├── Source Reconciliation
          └── Time Universe
          │
          ▼
Hierarchical analytical dataset
          │
          ├── EDA
          │     └── taxonomy candidates
          │
          └── Standard Report
```

## Data ownership

| Layer | Responsibility |
|---|---|
| Raw source | Preserve source truth |
| Source processor | Normalize one source |
| Integration | Combine sources without losing identity |
| Taxonomy | Define analytical meaning |
| Final analysis | Apply reconciliation and corrections |
| Time universe | Reconcile elapsed clock time |
| Hierarchy | Aggregate analytical dimensions |
| EDA | Investigate patterns |
| Standard Report | Summarize recurring KPIs |
| Historical layer | Compare periods |
| Budget | Future planning layer |

## Key invariant

```text
Clock Capacity
=
Unique Tracked
+
Off-Device Life
```

Analytical activity is not a clock ledger.
