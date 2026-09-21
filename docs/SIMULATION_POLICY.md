# SIMULATION_POLICY.md

## Mandatory scope

Isaac:
- PIPER-X environment;
- Quest/VR teleoperation;
- dataset recording;
- automated episode generation;
- policy evaluation.

MuJoCo:
- PIPER-X environment;
- policy evaluation.

## No universal simulator API

Use:

```text
policy contract
<-> sim-specific LeRobot processors/adapters
<-> native Gym/EnvHub/simulator environment
```

Raw native observation/action dictionaries may differ.

## Required simulator execution semantics

For each runtime resolve:

```text
physics timestep
control timestep
decimation/action repeat
control mode
actuator type
gains where relevant
saturation/ranges
action hold/interpolation semantics
reset seed/distribution
```

Do not claim Isaac and MuJoCo physics are equivalent. Make each side reproducible and explicit.

## Isaac

Prefer native upstream components:

```text
Isaac Lab
Isaac Teleop
RecorderManager
Mimic / SkillGen / native datagen
LeRobot Env/EnvHub evaluation seams
```

Use generic Piper/DoublePiper assets only as references unless exact PIPER-X equivalence is proven.

## MuJoCo

Prefer a Gymnasium environment and normal LeRobot environment processors/eval path. Build only the missing PIPER-X/task adapter.

## Processor contract

For both mandatory simulators resolve:

```text
native observation -> policy observation
policy action -> native action
```

Processor config/state/reset semantics are part of reproducibility.

## Cross-simulator parity

Interface parity:

```text
policy feature names/shapes
action names/shapes
units/gripper semantics
processor revisions
task identity
success/timeout semantics
horizon
```

Embodiment parity additionally includes home/zero, joint limits, positive direction, FK/TCP and gripper endpoints.

## Canonical VR composition

`./run-vr` and `./run-vr diag` share one scene, controller pipeline, processor,
IK, camera/XR setup and lifecycle. Modes select observers/side effects only.
The shared S2 config owns processor/clutch/gripper/tracking semantics; the canonical
VR config owns selected operator scene, presentation, controls and validation.
The optional external asset lab is experimental and loads its own manifest only
when selected. A composition object does not imply experimental gate scope.
Future recording must consume the same base runtime and preserve D0 temporal and
action-label boundaries. No D1 recorder or recording execution profile is selected.

## Three-camera observation boundary

Plain [[gate:S1]] qualifies native embodiment, control/reset behavior and the
state/two-wrist mapping. Its `observation()` compatibility API is a subset, not a
complete D0 v4 training source. Historical evidence retains its exact tested scope.
The human/automated Isaac source profiles own the complete training view; the VR
composition implements its three-camera production boundary. Recording admission,
XR identity, preclip action extraction and persistence remain pending.

VR advances the requested physics steps before one all-or-none capture. Reset
retains 24 settling steps plus the completion step. Preflight reaches its configured
settling boundary; the existing control-loop reset then establishes the first
eligible observation. Intermediate startup captures are explicitly non-evidence.
Steady state is observation at P, native target, four 120 Hz physics steps, then
one capture at P+4. No scheduler modulo determines observation eligibility.

A successful capture binds measured state, reset epoch, physics step, render
generation, and all three completed Camera generations/frame counters. Extraction
must finish without a producer change; a failed bundle publishes no identity.
Pixels remain in upstream buffers. `latest_observation_capture()` exposes immutable
identity/state only; `camera.capture.freeze()` optionally copies all three RGB
arrays at the unchanged boundary without acquisition, rendering or physics.
Consumers run on the simulation thread and must freeze before its next advance.
Identical pixel content is valid; producer association establishes freshness.

Startup/reset requires a valid bundle. During ordinary RUN a rejected bundle is
unavailable to capture consumers while existing camera health guards retain their
bounded-staleness policy. Diagnostic guards remain stricter. Future RECORD will
define admission/abort behavior separately. The shared RTX pump and 120 Hz render
cadence are unchanged; capture extraction occurs once per control boundary, even
when previews are hidden. No per-tick three-camera CPU snapshot is required.

The pinned Kit visualizer's `HEADLESS=1` path can skip its app pump while claiming
to own it. A Camera counter alone therefore cannot prove current RTX pixels. The
VR barrier requires a completed Kit app pump and rejects this unsupported headless
combination before publication. Canonical non-headless Kit rendering is the
qualified path; no extra render is issued to repair a missing pump. Headless
renderer support needs a separately qualified upstream configuration/fix.
