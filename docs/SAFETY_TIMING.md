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

Every accepted physical-profile asynchronous sample carries `sequence`, `source_timestamp`,
`clock_domain`, and `age_ms`. Age is computed only after timestamps are placed in a
common monotonic domain. Cross-modal skew is the maximum minus minimum source timestamp
for all physical inputs contributing to `obs_t` and `source_action_t`, including both physical XR poses for real human-VR sources and all three canonical
cameras: left_wrist, right_wrist, scene.

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

D0 v4 separates common causal transaction identity from source-profile timing.
Real human-VR recording [[gate:R2]] and per-arm HIL [[gate:HIL]] retain numeric
camera, joint, XR, action and skew enforcement: 75 ms camera/XR/skew and 45 ms
joint/action in the selected physical profile. CAN component receive timing,
oldest-component assembly and wall-to-monotonic calibration remain unchanged;
a wall-clock drift beyond the existing budget fails closed.

Isaac human recording [[gate:D1]] requires simulation generation, three-camera
capture barrier, XR session/DeviceIO/submitted/returned/resolved-input identities,
tracking validity, preclip action binding and completed transition/successor
proof. Host timestamps are QA/provenance, never physical XR acquisition time.
Automated Isaac generation [[gate:G1]] uses generator decision/revision/state/seed
identity and no XR stream. Neither Isaac profile inherits physical age paths.
These semantic declarations do not qualify the pending runtime bindings.

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
