# SAFETY_TIMING.md

## Machine-readable ownership

All resolved values below live in `../configs/resolved_contract.yaml`.

## Timing

Resolve independently:

```text
pacing, dataset, and source clock domains
physics FPS by runtime
XR FPS by runtime
camera FPS by canonical role
control FPS by runtime
dataset FPS
policy FPS
command FPS
Isaac physics/control dt and decimation
MuJoCo physics/control dt and decimation
max camera age
max joint age
max XR age
max policy-action age
max cross-modal skew
stale behavior
```

Equal numeric values do not imply one shared clock or one shared cadence. The canonical
dataset profile may remain 30 Hz while physics, acquisition, control, policy, and command
rates differ. With LeRobot action interpolation, `command_fps = policy_fps ×
interpolation_multiplier`; this does not change dataset FPS.

Every accepted asynchronous sample carries `sequence`, `source_timestamp`,
`clock_domain`, and `age_ms`. Age is computed only after timestamps are placed in a
common monotonic domain. Cross-modal skew is the maximum minus minimum source timestamp
for all physical inputs contributing to `obs_t` and `source_action_t`, including XR for
human-VR sources.

For chunk/RTC inference additionally resolve:

```text
inference mode
chunk horizon
execution horizon
interpolation multiplier
stale-chunk rule
age reference semantics
```

Chunk-only fields are required only for chunked modes.

### Source-freshness ownership

D0 defines the fields, clock semantics, and fail-closed enforcement phase; it does not
invent numeric limits without runtime evidence. Isaac human recording [[gate:D1]], real
human-VR recording [[gate:R2]], and per-arm HIL [[gate:HIL]] cannot be accepted until
`timing.max_camera_age_ms`, `timing.max_joint_age_ms`, `timing.max_xr_age_ms`, and
`timing.max_cross_modal_skew_ms` are numeric and enforced. Automated Isaac generation
[[gate:G1]] requires the camera, joint, and skew limits but does not synthesize an XR
stream.

Physical XR identity/session acceptance alone does not select or prove a numeric
source-pose age threshold. The earliest data/control gate owns the measured value and its
timestamped enforcement evidence.

## Low-level fail-safe [[gate:R1]]

Resolve and physically verify:

```text
owner
trigger
deadline_ms
safe effect
hardware evidence
```

A Python unit test does not prove a device-level fail-safe.

## Joint command safety [[gate:R1]]

Resolve:

```text
maximum step or slew policy
units
gripper range/polarity
residual clipping/smoothing behavior
```

Where observable, compare `dataset_action` and `device_accepted_command`; record residual modification rate/magnitude.

## Takeover continuity [[gate:HIL]]

Resolve a measurable takeover/release jump tolerance from evidence.

## Bimanual safety [[gate:R1B]]

Before shared real workspace:

```text
verified collision strategy
OR
conservatively disjoint workspaces
```

Workspace/collision artifacts are machine-referenced.

## Emergency stop

A reachable physical E-stop is required for first autonomous real rollout.

Simulation never proves real hardware watchdog/collision behavior.
