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

Logical dataset time and physical source time are different contracts:

```text
dataset_timestamp = frame_index / dataset_fps
source_timestamp  = physical acquisition time in a declared clock_domain
age_ms            = selection_time - source_timestamp
```

The LeRobot `timestamp` remains the dense episode-relative grid used for indexing and
video lookup. It is never evidence that a camera, joint state, or XR pose was acquired
at that logical instant. Every asynchronous input that contributes to an accepted frame
records `sequence`, `source_timestamp`, `clock_domain`, and `age_ms`; the frame also
records cross-modal skew. Freshness and skew are checked against the exact selected
bundle before both `Robot.send_action` and `LeRobotDataset.add_frame`.

`tools.d0_temporal.TemporalFrameRecorder` performs the validation and
`tools.temporal_recording.TemporalLeRobotDatasetAdapter` is the dataset-compatible
proxy passed to the unmodified upstream `record_loop`. The paired
`TimestampedTeleoperator` triggers validation before returning its action to that loop,
which is the last project-owned seam before upstream actuation. `add_frame` may only
commit that already validated bundle. A stale, future, clock-incomparable, skewed,
missing, repeated, or regressing bundle therefore reaches neither `Robot.send_action`
nor `LeRobotDataset.add_frame`. The violation aborts the current loop; the caller must
clear or discard the partial episode before continuing. LeRobot remains the owner of
logical `timestamp`, `frame_index`, pacing, processors, actuation, and episode
persistence. Saving or clearing an episode resets the adapter's episode-local sequence
history before the next episode.

The bounded recording profile uses 75 ms camera/XR age and cross-modal-skew limits,
and 45 ms joint/source-action age limits. The source rates remain independent: Isaac
physics is 120 Hz while XR, cameras, control, dataset, policy, and non-interpolated
command selection are each separately configured at 30 Hz. Equality is not a schema
constraint; the 30 Hz values are the selected profile. In the duplicate-free live
recording path, each required camera must nevertheless be configured at no less than
the dataset rate. Faster cameras are allowed and their intervening frames may be
dropped. No required source sample is silently reused, even if its age is still below
the limit.

PIPER-X CAN payloads contain no device acquisition clock. The timestamped SDK adapter
therefore captures the kernel SocketCAN receive timestamp separately for joint pairs
1/2, 3/4, 5/6 and the gripper, copies values and component identities atomically, and
uses the oldest required component time for the assembled state. This is an explicitly
declared lower-bound acquisition proxy, not the later observation-read time. Recording
mode performs a bounded wall-to-`perf_counter` calibration and stores the converted
host-monotonic value. Every temporal observation rechecks that conversion; a wall-clock
step or drift beyond the 5 ms calibration budget aborts recording instead of corrupting
source age.

A camera is stricter: its backend must implement
`async_read_with_acquisition_timing()` and atomically return a
`CameraAcquisitionSample` containing the selected frame, sequence, physical capture
timestamp, and clock domain. Standard `Camera.async_read()` state or a timestamp taken
after read, decode, or post-processing is rejected. Human-VR likewise requires one
atomic reader to return the action and the exact left/right XR pose identities used to
produce it. The existing Quest diagnostic's host receipt timestamp is not accepted as
XR acquisition time.

For every native recorder/converter, resolve:

```text
native field -> obs_t
native field -> action_t
native field -> outcome_t / termination / success
```

## Causality regression test

Before [[gate:D0]] acceptance, run a distinguishable synthetic trajectory such as:

```text
obs_t = t
action_t = 1000 + t
```

After recording/conversion, verify exact pairs `(obs_0, action_0)`, `(obs_1, action_1)`, etc.

Timestamp monotonicity alone does not prove causal pairing. A temporal regression
must also prove that stale source samples and excessive cross-modal skew are rejected,
and that the logical dataset timestamp is never substituted for source acquisition time.

## Common training view

Classify features as:

```text
training_input
training_target
evaluation_only
provenance_only
privileged_debug
```

The exact policy-input set is whitelist-checked.

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
