# DATA_COLLECTION_POLICY.md

## Final dataset owner

All final training data uses LeRobotDataset v3.

Required canonical source records:

```text
runtime=real,  source_class=human_vr
runtime=isaac, source_class=human_vr
runtime=isaac, source_class=<automated canonical source>
```

Do not permanently encode runtime+source as aliases such as `isaac:generated`.

## Source taxonomy

Canonical values:

```text
[[source:human_vr]]
[[source:scripted_expert]]
[[source:planner]]
[[source:datagen]]
[[source:policy_generated]]
[[source:replay_or_transform]]
```

This is semantic provenance, not a Python class hierarchy.

## Temporal semantics

Canonical transition `t`:

```text
obs_t
-> human / expert / planner / policy decision
-> source_action_t
-> deterministic label processors
-> dataset_action_t
-> runtime-specific native actuation mapping
-> environment/robot transition
-> outcome_t and obs_t+1
```

The stored BC pair is `(obs_t, dataset_action_t)` unless a later contract revision explicitly changes the learning target.

D0 v4 selects a temporal profile by `(runtime, source_class)`. Common causal
identity binds run, episode, source, reset epoch, control-reference epoch,
source/session epoch, control tick, observation, dataset action, native command,
transition, and successor observation. The neutral `CausalTransactionValidator`
prepares immutable payload digests/source identities, completes a successful
transition, then commits only the original observation/action payloads. Abort or
epoch change invalidates the pending transaction. Duplicate source identities,
wrong ticks, repeated transitions and payload substitution fail closed. Edges must
serialize dtype, shape, role and content unambiguously or use immutable
content-addressed references; large images are not retained in the validator.

The logical LeRobot timestamp remains `frame_index / dataset_fps` for indexing
and video lookup. It never proves physical acquisition or simulation capture.

- `isaac_human_vr_v4`: simulation state generation and live three-camera capture identity;
  XR session epoch, DeviceIO update, submitted frame, returned frame, resolved input
  payload identity and tracking validity. Host begin/end times are optional QA and
  provenance, **not XR physical acquisition time**. Exact OpenXR query time is
  optional when explicitly exposed. The source action is the post-DifferentialIK
  desired joint target **before native clipping**, converted to canonical deg/mm.
  Its accepted D0 evidence remains scoped to this profile; it is not evidence for
  the additive offline-RGB profile below. The runtime binding remains pending D1.
- `isaac_human_vr_offline_rgb_v1`: the selected recording profile uses an
  immutable pre-action scene-state snapshot as the online observation source.
  Online admission requires the snapshot identity plus the exact XR DeviceIO,
  submitted-frame, returned-frame and resolved-input identities used by the
  post-DifferentialIK preclip action. The scene snapshot identity binds run,
  episode, source and reset/reference/session epochs, control tick, `obs_id`,
  snapshot ID and digest, simulation-state generation and physics step. It does
  not claim that absent live pixels were captured online. Offline materialization
  must produce `offline_rgb.left_wrist`, `offline_rgb.right_wrist`, and
  `offline_rgb.scene`; each identity binds `obs_id`, snapshot ID/digest, camera
  role and prim path, camera and renderer configuration digests, stage-snapshot
  and asset-closure digests, materialization revision and RGB digest. The join is
  exact on `obs_id` and scene-state-snapshot digest; positional joins are
  forbidden. This declaration is pending implementation and D1 evidence, and a
  native state recording remains `dataset_admissible=false` until the three
  camera roles are materialized and the D1 requirements pass.
- `isaac_automated_v4`: the same simulation/camera/transition identities, with
  generator decision/revision/state and seed when applicable. No XR is synthesized.
- `real_human_vr_physical_v4`: causal identity plus strict physical timing for state,
  left wrist, right wrist, scene, both XR poses and source action. Each physical
  sample carries sequence, source timestamp, clock domain and age; the frame carries
  cross-modal skew. `PhysicalTimingValidator` retains age/skew, future time,
  clock-domain and repeated/regressing sequence rejection.

Isaac persistence follows successful transition and successor observation.
The real LeRobot persistence seam remains after `send_action`, before the next tick:
`TimestampedTeleoperator` validates source timing before returning the action;
`TemporalLeRobotDatasetAdapter` commits the prepared metadata at `add_frame`.
The explicit `TemporalFrameRecorder.commit_transaction_frame` bridge checks the
actual typed frame against an already prepared real transaction at this seam;
causal commit still waits for its successor. Legacy upstream integration remains
compatible, and full source-runtime identity binding is pending R2.
LeRobot owns processors, logical time, pacing and episode persistence. This seam
alone cannot attest hardware acceptance or a successor observation; full real
source admission must additionally demonstrate the paired transition/successor.
A physical timing failure aborts before actuation and persistence; the caller must
clear/discard the partial episode. Saved/cleared episodes reset timing history.

Physical camera/XR and cross-modal-skew limits remain 75 ms; joint/source-action
limits remain 45 ms. CAN clock calibration behavior is unchanged. Rates remain
independent; the duplicate-free physical recorder requires each camera rate at
least the dataset rate. Isaac instead needs a qualified three-camera capture
barrier for the selected simulation generation. No source is silently reused.

PIPER-X CAN payloads contain no device acquisition clock. The timestamped SDK adapter
therefore captures the kernel SocketCAN receive timestamp separately for joint pairs
1/2, 3/4, 5/6 and the gripper, copies values and component identities atomically, and
uses the oldest required component time for the assembled state. This is an explicitly
declared lower-bound acquisition proxy, not the later observation-read time. Recording
mode performs a bounded wall-to-`perf_counter` calibration and stores the converted
host-monotonic value. Every temporal observation rechecks that conversion; a wall-clock
step or drift beyond the 5 ms calibration budget aborts recording instead of corrupting
source age.

In the real physical profile, a camera is stricter: its backend must implement
`async_read_with_acquisition_timing()` and atomically return a
`CameraAcquisitionSample` containing the selected frame, sequence, physical capture
timestamp, and clock domain. Standard `Camera.async_read()` state or a timestamp taken
after read, decode, or post-processing is rejected. Real human-VR likewise requires one
atomic reader to return the action and the exact left/right XR pose identities used to
produce it. The existing Quest diagnostic's host receipt timestamp is not accepted as
XR acquisition time.

For every native recorder/converter, resolve:

```text
native field -> obs_t
native field -> action_t
native field -> outcome_t / termination / success
```

For `isaac_human_vr_offline_rgb_v1`, one admitted native HDF row is exactly one
completed causal transaction `(O_t, A_t, O_(t+1))`. The row is appended only after
successful native transition, successor observation, causal completion and commit:

- `O_t` stores the pre-decision canonical float32[14] state in ordered joint
  degrees/gripper millimetres and its immutable scene-state-snapshot reference;
- `A_t` stores the post-IK, pre-native-clipping canonical float32[14] label in the
  same degree/millimetre order;
- the native preclip, clipped and residual float32[14] vectors use joint radians
  and gripper metres, with saturation represented separately;
- the transition stores its identity and outcome/termination/success/failure
  classification;
- `O_(t+1)` stores the post-transition canonical state and successor identity.

The HDF row index is a dense zero-based commit order, not a control-tick identity;
control ticks may have gaps. An invalid, held, tracking-invalid, reset-crossing or
failed tick appends no row and only increments reasoned episode QA. A genuine
committed zero action remains valid and is never inferred from value alone. The
last admitted action still requires a successor observation and terminal outcome
in the same row; there is no actionless terminal row. A missing successor aborts
the pending transaction, and an episode with zero commits is lifecycle-only and
not dataset-admissible.

## Causality regression test

Before [[gate:D0]] acceptance, run a distinguishable synthetic trajectory such as:

```text
obs_t = t
action_t = 1000 + t
```

After recording/conversion, verify exact pairs `(obs_0, action_0)`, `(obs_1, action_1)`, etc.

Timestamp monotonicity alone does not prove causal pairing. D0 offline evidence
must reject action t-1/t+1, payload substitution, reset/reference/session epoch
crossing, incomplete or wrong-tick transitions and duplicate commits. Profile
isolation proves Isaac does not need physical XR time, while real human-VR does.
Physical regression also rejects stale/future/missing timing, skew, clock mismatch,
and repeated/regressing sources; logical time cannot replace acquisition time.

## Common training view

Classify features as:

```text
training_input
training_target
evaluation_only
provenance_only
privileged_debug
```

The exact ordered canonical schema is:

```text
observation.state
observation.images.left_wrist
observation.images.right_wrist
observation.images.scene
task
action
```

The first five features are the policy-input whitelist; `action` is the target.
All three cameras capture uint8 RGB `[480,640,3]` and expose float32 RGB
`[3,480,640]` in `[0,1]`. There is no canonical crop, resize or flip. Native
camera/device names belong in source bindings, never canonical role names.
State and action remain float32[14], left six joints in degrees and gripper in
millimetres, then the same right-arm order. Native clipping never replaces labels.

Simulator ground-truth state must not enter a real-deployable policy through implicit passthrough.

## Provenance

At minimum identify:

```text
runtime
source_class
task_id / task_revision
embodiment_revision
processor_contract_revision
dataset/source revision
generator/planner revision where applicable
source demonstration lineage where applicable
generator/randomization seed where applicable
policy checkpoint where applicable
conversion revision
```

Use native LeRobot metadata where suitable. A versioned sidecar/manifest is allowed when necessary.

## Failed/aborted episodes

Do not silently mix:

```text
success
failure
timeout
abort
tracking-stale
```

The QA report classifies them.

## Immutable source datasets

Keep source/canonical datasets identifiable. A mixed training dataset should be reproducibly materialized rather than destructively replacing the only source copy.

## Source admission

A future source declares its temporal profile, ordered `physical_source_name` ->
`canonical_feature_key` camera bindings, preprocessing revision and registered
calibration references, plus immutable dataset/manifest identity. All three camera
roles and the current canonical fingerprint are mandatory. `dataset.sources`
remains empty: real three-camera source requirement defined; actual source
registration remains pending (UNREGISTERED / EVIDENCE PENDING). The legacy
RoboSyn 25 FPS dataset is not registered or qualified by this contract migration.
