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

## Isaac VR executable materialization path

The snapshot/offline-RGB source intentionally spans two isolated environments:
the pinned Isaac environment owns HDF5 extraction, while the core environment
owns LeRobot 0.6.1. Run the repository orchestrator from the core environment
and name the Isaac interpreter explicitly:

```sh
.venv/bin/python tools/isaac_vr_lerobot_materialize.py orchestrate \
  --extract-python /path/to/pinned-isaac/bin/python \
  --recording /private/recording/session.hdf5 \
  --replay-report /private/replay/result.json \
  --output /private/materialized/dataset \
  --repo-id local/immutable-dataset-id \
  --task-id dual_cube_to_matching_plates \
  --portable-root recording=/private/recording \
  --portable-root project_assets=/path/to/project/assets \
  --portable-root isaac61_production=/path/to/isaac/runtime
```

Every output path must be new. The command fails before publication on a native
row, terminal successor, closure, provenance, image identity, digest, task,
video-decode, or DataLoader mismatch. It never promotes the result to an
admissible dataset: the materialization manifest retains explicit admission
blockers until physical source qualification and the owning D1 decision exist.

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
Isaac human live profile: capture barrier and resolved XR identities, not acquisition time
Isaac human offline-RGB profile: scene-state snapshot identity, three materialized camera identities and exact digest join
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

For the selected Isaac human snapshot/offline-RGB profile, replay is materialization,
not evidence that live camera pixels existed during teleoperation. Each of the three
canonical RGB outputs must be rendered from the exact immutable `O_t` scene-state
snapshot named by the committed native row. The materializer records and verifies
the snapshot, stage, asset-closure, camera-configuration, renderer-configuration,
materialization-revision and output-RGB digests. It joins images to state/action by
`obs_id` and scene-state-snapshot digest; row/list position is not a join key.

The native HDF is not a D1 dataset by itself. Projection may admit a row only when
all three materialized camera identities exist and verify against the same `O_t`.
Missing, duplicate, mismatched or extra-role images fail closed. The projected BC
sample is `(O_t, A_t)`; `O_(t+1)` and transition/outcome remain provenance and QA
for causal verification rather than silently shifting the learning pair.
