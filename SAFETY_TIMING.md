# SAFETY_TIMING.md

## Machine-readable ownership

All resolved values below live in `configs/resolved_contract.yaml`.

## Timing

Resolve:

```text
clock domain
dataset FPS
teleop sampling FPS
camera FPS by canonical role
policy inference FPS
robot command FPS
Isaac physics/control dt and decimation
MuJoCo physics/control dt and decimation
max XR pose age
max joint-state age
max policy-action age
stale behavior
```

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

### XR pose-age ownership

Physical XR identity/session acceptance does not select or prove a numeric source-pose
age threshold. Resolve and enforce `timing.max_xr_pose_age_ms` at each earliest real
teleop-to-robot-control boundary: real human-VR recording [[gate:R2]] and per-arm HIL
[[gate:HIL]]. Both gates fail closed while the value or its timestamped enforcement
boundary is unresolved.

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
