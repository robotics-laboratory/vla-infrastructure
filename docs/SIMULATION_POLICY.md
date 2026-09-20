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
