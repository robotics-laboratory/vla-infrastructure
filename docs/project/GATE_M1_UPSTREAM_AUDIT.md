# Gate M1 upstream audit

Status: M1 reopened on 2026-09-25 after physical Quest runs contradicted the earlier gripper-retention evidence; v20 automated NVIDIA EGL revalidation passed on 2026-09-29 and physical Quest validation remains required.

## CAPABILITY / GATE

Gate M1: a reproducible PIPER-X MuJoCo environment. The current increment covers the canonical
single-arm model, bimanual composition, direct physical-finger actuation, the frozen task scene, three named
cameras, a concrete Gymnasium lifecycle, and D0/native processors. The executable evidence runner
and registered parity report close the M1 environment scope only; policy evaluation remains E2 and
was not started.

## PINNED UPSTREAM CANDIDATES

- MuJoCo `3.9.0`, revision `237c17e48539b6c90bf90d3161547cbdcbfaa1e0`;
- Gymnasium `1.3.0` for the later environment lifecycle;
- LeRobot `0.6.1` for the later policy processor/evaluation seam;
- AgileX `agx_arm_urdf` revision `f6642ce0d7872c686f29c99e9e10cd23d1d49313`;
- the accepted Gate C PIPER-X model and FK/direction references.

## WHAT UPSTREAM ALREADY OWNS

- URDF parsing and native MJCF serialization through `mujoco.MjSpec`;
- model compilation, named access, equality constraints, actuators, contacts, and stepping;
- build-time attachment with deterministic left/right prefixes;
- rendering through `mujoco.Renderer` and lifecycle/registration through `gymnasium.Env`;
- processor composition and serialization boundaries through LeRobot `ActionProcessorStep`,
  `ObservationProcessorStep`, and `ProcessorStepRegistry`.

## EXACT REMAINING GAP

- compose the frozen table, cubes, plates, lighting, wrist views, and debug scene view;
- map D0 degrees/signed millimetres to native radians/metres while preserving `dataset_action_t`;
- map named native qpos and wrist RGB into the exact D0 observation keys;
- implement fixed Level-0 reset, settling, control repetition, task predicates, reward,
  termination, and truncation in one concrete environment;
- prove reset/step/render operation under EGL and retain earlier embodiment parity checks;
- ensure each wrist optical axis points along the gripper approach direction and validate it with a rendered marker;
- represent the flat grasping surfaces separately from the tapered imported visual meshes and hold both physical fingers under closed-grasp and open-arm-motion load;
- preserve the 14-value native command while expanding each scalar aperture only inside the concrete environment to `+0.5/-0.5` physical-finger targets.

## PROCESSOR / CONFIG / ADAPTER REQUIRED

The implementation uses one deterministic build tool, one frozen runtime/task config, two
PIPER-X-specific LeRobot processor steps, and one concrete Gymnasium environment. No generic
simulator adapter is introduced. MuJoCo's single sliding friction coefficient cannot exactly encode
the requested static/dynamic pair, so the scene uses `0.8` and records that approximation.

The 2026-09-25 repair remains below a framework boundary: the deterministic PIPER-X builder adds
two fixed fingertip pads, corrected named-camera axes, and two bounded physical-finger actuators.
It removes the conflicting compatibility-leader actuator and its two leader/follower constraints.
After run 7 exposed grasp-center drift between fully independent fingers, v9 adds one physical
`q1=-q2` relation while keeping the two consistent direct `+0.5/-0.5` targets. The constraint uses
the previously stable MuJoCo solver reference after the overly stiff first candidate lost contact
in the retained grasp regression. This does not change
D0, `dataset_action_t`, or the 14-value native action. MuJoCo still owns contacts, constraint and
servo dynamics, rendering, and all integration.

The retained-grasp verifier expresses cube position in the moving gripper frame
before measuring translation. The v14 diagnostic localized its 20.144 mm shift
almost entirely along the pad tangent. V15 selects MuJoCo's existing six-
dimensional contact for the pads so their already declared torsional and rolling
friction terms are active rather than ignored by the default `condim=3`. This is
a contact configuration correction, not a new controller or acceptance-limit
relaxation.

The v16 renderer excludes imported collision group 0 from cameras and keeps
visual meshes plus task geometry in group 1. Physics and contact still use the
collision meshes. This removes coincident-mesh z-fighting that changed 22
right-wrist channel values by one LSB after otherwise identical steps.

Physical run 10 showed that the remaining problem was not an IK mapping change:
Cartesian saturation and IK failures stayed at zero. The old finger collision
box instead covered the complete `56 x 76 x 12 mm` mesh bounding rectangle,
including proximal and side volume that is not a cube-facing grasp surface.
M1 v17 retains the v16 controller, equality, force, friction, and rendering
configuration, but replaces each box with one thin distal pad at
`[0, -0.055, 0.001] m`, half-extents `[0.024, 0.021, 0.001] m`. MuJoCo still
owns all contact resolution; this is a source-geometry correction only.

Physical run 11 confirmed progress: arm reach was restored and a closed command
repeatedly established cube contact at `36-38 mm`, but the cube later slipped
and the fingers closed to nearly zero. At the nominal cube pose, only about
`24 mm` of its `40 mm` longitudinal face overlaps the distal-only pad. The v18
candidate extended contact with an angled proximal pad, but the focused offset
regression lost the left cube at tick 240 while symmetry remained `0.003 mm`
and aperture collapsed to `2.073 mm`. That isolates the failure to edge/wedge
contact rather than finger tracking. M1 v19 replaced both pieces with one thin
coplanar `40 x 66 x 2 mm` grasp insert spanning the working length, but matching
the cube width exactly left no lateral margin: its focused regression lost
contact earlier at tick 215 despite `0.004 mm` symmetry. M1 v20 restores the
previously successful `48 mm` width while retaining the continuous `66 mm`
length and `2 mm` thickness. That gives a 40 mm cube 4 mm margin per side and
remains narrower and six times thinner than the rejected bounding box. No
controller, force, friction, equality, action, or acceptance bound changes.

## ENVIRONMENT IMPACT

The build, processors, environment, and tests run in the existing `core` environment with pinned
MuJoCo `3.9.0`, Gymnasium `1.3.0`, and LeRobot `0.6.1`. EGL provides headless rendering. No new
environment, container, service, or RPC boundary is introduced.

## WHY NO PROJECT FRAMEWORK IS NEEDED

MuJoCo owns model parsing, attachment, constraints, actuation, contacts, simulation, and rendering;
Gymnasium owns the lifecycle API; LeRobot owns processor composition. Project code only closes the
PIPER-X-specific model conversion, task predicates, reset, and the exact D0/native semantic edge.

## Code-size re-audit

The build tool is slightly above the approximate 300 LOC re-audit threshold. The extra code is
bounded provenance and validation work: Git/source checks, deterministic mesh copying, canonical
XML emission, manifest hashes, and compile-time dimension checks. It does not introduce a
simulator backend, registry, dataset abstraction, FK/IK implementation, or runtime framework.

The first dynamics probe exposed adjacent convex-hull contacts between `base_link` and `link1`.
The implementation excludes only direct URDF parent/child body pairs, retains all other collision
pairs, and uses MuJoCo `implicitfast` at the candidate 240 Hz physics rate. The regression test requires
zero initial contacts, finite state, and less than `1e-3` rad/m maximum qpos drift over the 120-tick
model-only settling smoke.

Production runtime code remains below the 1000-LOC one-gate threshold: the concrete environment,
processors, constants, registration, smoke runner, and interactive launcher total 565 lines. Two
offline tools exceed the 300-LOC module threshold and were re-audited: the 564-line builder owns deterministic source/model/
scene provenance, while the verifier owns Gate C parity, Gymnasium checking, camera-axis and role
probes, 1000-reset stress, open-aperture retention, bilateral grasp retention, task/contact lifecycle, memory, and performance evidence. They
are not runtime frameworks or policy paths, share no generic simulator abstraction, and do not
replace MuJoCo, Gymnasium, LeRobot evaluation, FK/IK, recording, or datasets.
