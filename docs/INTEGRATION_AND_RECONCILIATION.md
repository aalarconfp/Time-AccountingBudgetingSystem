# Integration and Reconciliation

## Purpose

This layer turns multiple observations into a defensible analytical and
elapsed-time accounting model.

## Three concepts

### 1. Recorded time

Original source-observed duration.

### 2. Corrected tracked time

Recorded time after explicit corrections.

### 3. Unique tracked time

Corrected tracked time after removing overlap between tracked sources.

```text
Unique Tracked = Corrected Tracked - Overlap
```

## Off-Device Life

```text
Off-Device Life = Clock Capacity - Unique Tracked
```

It represents legitimate human activity outside digital tracking.

## Adjustment types

### Habit adjustment

Example:

```text
Family Time Tracking -120 min
```

The category itself was overstated.

### Classification removal

A specific analytical classification is removed from its current category.

### Attribution redirect/removal

The time is not correctly attributed to the current observer.

For shared-device attribution (time a secondary user spent on a shared
device), the rule configured in `config/settings.py` redirects matching
negative Habit adjustments to:

```text
ActivityWatch <shared device> / Uncategorized
```

which is the intended target when available.

Apple Screen Time is not reduced for this correction.

## Capping

If requested time exceeds available target time:

```text
Applied = Available
Unapplied = Requested - Available
```

The unapplied amount must remain visible in the audit.

## Review philosophy

A reconciliation review is information, not failure.

Do not force all days to appear normal by inventing time or silently discarding
exceptions.
