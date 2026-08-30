# DATASET_MATERIALIZATION.md

## Baseline workflow

"Compatible training view" is not enough. The accepted route must be executable by the selected LeRobot data/training stack.

```text
real human source dataset
Isaac human source dataset
Isaac automated source dataset
        |
        v
deterministic source-specific projection/conversion
        |
        v
identical canonical final feature schema
        |
        v
materialized/merged LeRobotDataset v3
        |
        +-> full frame iteration
        +-> every video stream decode/read
        +-> DataLoader smoke
        +-> optional short training compatibility smoke
```

Do not create a runtime multi-dataset abstraction merely to avoid materialization.

## Schema fingerprint

Each projected source records a SHA-256 schema fingerprint derived from the canonical ordered feature specification.

Before [[gate:DM]] is accepted:

```text
all projected source schema fingerprints
==
final training dataset schema fingerprint
```

## Final dataset identity

Identify the final dataset immutably, for example:

```text
Hub repo + revision + local manifest hash
or
local manifest + artifact hashes
```

`latest` is not an immutable identity.

## Full-read QA [[gate:DQ]]

A metadata-only open is insufficient.

Cover:

```text
all episodes
all frames
all configured video streams
DataLoader iteration
episode boundaries
obs/action pairing
units/order
success/termination
camera role mapping
NaN/Inf
timestamp monotonicity
duplicate timestamps
frozen/empty camera streams
large joint discontinuities
stale XR intervals
action saturation/residual modification rates where available
abort/timeout classification
```

Task/hardware thresholds remain resolved experimental values rather than guessed constants.

## Replay

Use semantic replay/inspection where applicable. Do not require pixel-perfect replay from nondeterministic physics resets.
