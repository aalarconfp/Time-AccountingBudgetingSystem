# Taxonomy and EDA

## Taxonomy hierarchy

```text
Category
  ↓
Subcategory
  ↓
Domain
  ↓
Energy
  ↓
Goal
```

## Reference files

```text
output/Reference/Taxonomy/
```

## Taxonomy changes

Change taxonomy only when the mapping is genuinely wrong or the analytical
definition intentionally changes.

Process:

1. identify mapping;
2. edit reference source;
3. rebuild taxonomy;
4. validate;
5. rerun final analysis;
6. rerun EDA;
7. rerun Standard Report.

## EDA purpose

EDA is for:

- pattern discovery;
- concentration;
- large contributors;
- taxonomy candidates;
- Uncategorized review;
- Off-Device Life analysis;
- cross-device analysis;
- trend preparation.

## Large-node rule

A large node is not automatically a bad classification.

Review:

- Sleep;
- Games;
- Education;
- Office Tools;
- Family Time;
- Off-Device Life;
- other large nodes

before changing taxonomy.

## Utilities

System utilities are classified according to their analytical meaning.

Current example:

```text
ActivityWatch / System Processes
Category: Utilities
Domain: Vocational
Energy: Shallow
Goal: Maintenance
```

## Off-Device Life

Current analytical mapping:

```text
Category: Off-Device Life
Subcategory: Untracked Maintenance
Domain: Physical
Energy: Active
Goal: Maintenance
```

This should be treated as meaningful human-life maintenance.

## Burnout interpretation

One period is insufficient to infer burnout.

Monitor repeated periods for:

- decreasing Recovery;
- decreasing Deep energy;
- decreasing Off-Device Life;
- increasing discretionary consumption;
- decreasing Investment;
- excessive Maintenance load.
