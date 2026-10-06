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
Isaac Sim Episode Recorder SessionStorage / Recordables / EpisodeReplayer
Isaac Lab RecorderManager
Mimic / SkillGen / native datagen
LeRobot Env/EnvHub evaluation seams
```

Use generic Piper/DoublePiper assets only as references unless exact PIPER-X equivalence is proven.

The selected human recorder uses upstream Episode Recorder `SessionStorage` for
native HDF5 persistence/buffering and public `Recordable` tracks for state.
The project `ExplicitFrameSampler` owns sampling at the causal control boundary
and appends committed rows; it does not instantiate an `EpisodeRecorder` scheduler
or route this path through Isaac Lab `RecorderManager`. Replay uses upstream
`SessionReader` and `EpisodeReplayer` after project integrity checks. Native
generation workflows remain candidates for the separate automated source.

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
Recording consumes the same base runtime and preserves D0 temporal and action-label
boundaries. The selected `isaac_vr_record` execution profile writes a native
snapshot/state/action/provenance artifact under the additive
`isaac_human_vr_offline_rgb_v2` source profile. Native recording, strict replay and
LeRobotDataset v3 conversion are implemented. Implementation and contract
selection do not establish source admission or resolve D1; canonical RGB requires
verified offline materialization, and gate acceptance requires the registered
physical/source and dataset evidence.

## Three-camera observation boundary

Plain [[gate:S1]] qualifies native embodiment, control/reset behavior and the
state/two-wrist mapping. Its `observation()` compatibility API is a subset, not a
complete D0 v4 training source. Historical evidence retains its exact tested scope.
The human/automated Isaac source profiles own the complete training view; the VR
composition implements its live three-camera production boundary. RUN/DIAG expose
the resolved-XR/post-IK preclip decision seam; RECORD consumes the shared control
solution with its snapshot-backed observation and completed causal persistence.
Their bounded implementation checks do not accept a dataset or physical human
operation. Source and completed-demo admission remain subject to D1 evidence.

RUN/DIAG advance the requested physics steps before one all-or-none live capture.
Reset retains 24 settling steps plus the completion step. Preflight reaches its configured
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

RUN/DIAG startup/reset requires a valid live bundle. During ordinary RUN a rejected
bundle is unavailable to capture consumers while existing camera health guards retain their
bounded-staleness policy. Diagnostic guards remain stricter. RUN/DIAG retain the
RTX pump per physics integration; capture extraction occurs once per control
boundary, even when previews are hidden. Physics/control/capture rates describe
simulation time, not achieved wall-clock throughput. Preview publication has its
own host-time limit. No per-tick three-camera CPU snapshot is required.

The pinned Kit visualizer's `HEADLESS=1` path can skip its app pump while claiming
to own it. A Camera counter alone therefore cannot prove current RTX pixels. The
VR barrier requires a completed Kit app pump and rejects this unsupported headless
combination before publication. Canonical non-headless Kit rendering is the
qualified path; no extra render is issued to repair a missing pump. Headless
renderer support needs a separately qualified upstream configuration/fix.

## Snapshot-backed recording boundary

The offline-RGB recording profile is distinct from the live three-camera boundary
above. Before native actuation it freezes a content-addressed scene-state snapshot
for `O_t`, including the canonical measured state and every world/camera state
needed for later rendering. It must not reuse a later post-transition state or
claim live camera identities. After `A_t` is applied and the successor `O_(t+1)`
is captured, the runtime completes and commits the causal transaction before one
native row can be appended. Invalid loops append no data row.

RECORD preserves canonical Camera prims and Recordables but suspends their live
dataset RenderProducts/annotators. It reads no live canonical RGB. The shared
native transition still has four physics integrations; rendering/app pumping is
selected only for the final integration (`F,F,F,T`). RECORD reset performs the
shared 25 settling integrations with only the final render/pump, then returns
measured state for the recorder's immutable capture. Startup preflight before
recording setup and RUN/DIAG retain their live rendering path. These implemented
schedules do not establish physical performance or recording qualification.

Replay opens the recorded stage and applies the immutable `O_t` snapshot without
advancing physics, then materializes left-wrist, right-wrist and scene RGB for
every admitted observation. Replay verifies complete track binding and zero
physics callbacks; it does not construct the current task scene or rerun actions.
The rendered identities bind the snapshot and the full stage/asset/camera/renderer
inputs. Until those three outputs exist and D1 evidence passes, the native artifact
is explicitly not a canonical dataset.
