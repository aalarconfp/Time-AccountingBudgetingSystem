# Source Processing SOP

## Principle

Each source is normalized independently before integration.

## Order

```text
ActivityWatch laptop
ActivityWatch desktop
Apple Screen Time
Habit / Off-Device
        ↓
Integrated daily files
```

## Validation

For each source:

- expected dates exist;
- durations are non-negative;
- no accidental duplicate ingestion;
- categories/activity names are recognized;
- device identity is preserved.

## Integration rule

Integration should combine records, not erase provenance.

Every integrated record should remain attributable to its source/device.

## Failure handling

If a source processor fails:

1. stop;
2. preserve the error;
3. inspect the source input;
4. fix the source-processing issue;
5. rerun;
6. validate the generated output.

Do not patch the final analysis to conceal a source-processing failure.
