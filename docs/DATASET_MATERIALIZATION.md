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

Each projected source records the SHA-256 from the project implementation's
canonical ordered specification: `observation.state`,
`observation.images.left_wrist`, `observation.images.right_wrist`,
`observation.images.scene`, `task`, `action`. Camera capture is uint8 RGB HWC
[480,640,3], policy input float32 CHW [3,480,640] in [0,1], without canonical
crop/resize/flip. Source manifests declare physical-name-to-canonical-role
bindings, preprocessing revision, calibration references and temporal profile.
D2 parity compares this three-camera schema and profile-appropriate causal proof;
physical timing fields are not fabricated for Isaac.

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
all three canonical video streams, with no omitted scene stream
DataLoader iteration
episode boundaries
obs/action pairing
units/order
success/termination
camera role mapping
NaN/Inf
dataset timestamp monotonicity
common causal identities, epochs, transition/successor and immutable payload binding
source-profile parity and dispatch by runtime/source_class
physical profiles: timestamp/sequence monotonicity by clock domain
physical profiles: camera/joint/XR/action age and cross-modal skew
Isaac human: capture barrier and resolved XR identities, not acquisition time
Isaac automated: generator identity/provenance, no XR
duplicate logical timestamps and repeated source sequences
frozen/empty camera streams
large joint discontinuities
physical stale XR intervals; Isaac tracking-invalid/resolved-input gaps
action saturation/residual modification rates where available
abort/timeout classification
```

Task/hardware thresholds remain resolved experimental values rather than guessed constants.

## Replay

Use semantic replay/inspection where applicable. Do not require pixel-perfect replay from nondeterministic physics resets.
