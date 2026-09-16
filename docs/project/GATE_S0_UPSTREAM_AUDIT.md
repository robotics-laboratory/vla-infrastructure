# Gate S0 upstream audit — Isaac repin amendment

Audit date: 2026-09-08
Reopened gate: S0 only
Verdict: **RE-ACCEPTED**

The current selection is Candidate B, `release/3.0.0` at exact commit
`913ac53f51b2f8d02c9e121caa4cbdd06262948e`. The superseded-pin and rejected-
candidate history is retained only in the registered, explicitly historical
`GATE_S0_ISAAC_COMPATIBILITY_REMEDIATION.md` artifact.

The qualification bundle at
`/data/vla-infrastructure/isaaclab_candidate_qualification/20260907/` was checked with
`sha256sum -c MANIFEST.sha256`; every registered file passed. The exact commands,
host facts, results, logs, package inventory, conflict output, and source checkouts
are retained there.

## Mandatory upstream audit

| CAPABILITY / GATE | PINNED UPSTREAM CANDIDATES | WHAT UPSTREAM ALREADY OWNS | EXACT REMAINING GAP | PROCESSOR / CONFIG / ADAPTER REQUIRED | ENVIRONMENT IMPACT | WHY NO PROJECT FRAMEWORK IS NEEDED |
|---|---|---|---|---|---|---|
| S0/S1 Isaac runtime | Candidate B `913ac53f…`; rejected candidates are recorded only in the remediation artifact | AppLauncher, Kit lifecycle, PhysX/Fabric, articulation, reset, Camera renderer backend | none for accepted S1; local scope is the Gate C binding, task, D0 edge, and parity evidence | one Isaac-specific config, D0 edge processors, concrete runner | isolated Candidate B frozen uv workspace; LeRobot absent | upstream owns application, simulation, rendering, and sensors |
| S1 bimanual cameras | Candidate B `913ac53f…` | parented `Camera` prims, regex-batched Camera view, pose propagation, RGB publication, reset | none for accepted S1; local scope is exact wrist bindings, D0 role keys, and current regression evidence | direct `CameraCfg`, no camera abstraction | same isolated Isaac environment | upstream native two-camera form passed 440/440 frames |
| S1 PIPER-X embodiment/control | Isaac Lab B plus Gate C asset `f6642ce…` | URDF conversion, Articulation, implicit actuators, joint targets | none for accepted S1; local scope is deterministic composition, two namespaces, D0 unit/order conversion, and parity | thin asset materializer and named mappings | generated USD/cache stays under `/data/vla-infrastructure` | no duplicate FK/IK or robot backend is needed |
| S2 Isaac Quest/XR | Candidate B `913ac53f…`; frozen `isaacteleop==1.4.98rc1`; in-tree `isaaclab_teleop==0.8.0` | XR experiences, session lifecycle, controller sources, rebase and retargeting seams | physical PIPER-X mapping/behavior evidence after automated qualification | one concrete S2 processor/config only | expanded frozen surface rechecked with the same 11 conflicts and no new conflict | S1 does not justify an XR or CONTROL framework |
| D1/G1 native recording/generation | Candidate B `913ac53f…` | RecorderManager, HDF5 handler, manager/task patterns | later D0 recorder terms/conversion and task-local source | deferred to D1/G1 | same environment, rechecked when expanded | upstream recorder remains authoritative |
| E1 evaluation | LeRobot `7e241bd…` in core; Candidate B in Isaac | LeRobot policy/eval and native Isaac environment | transport/endpoint/run manifest | deferred E1 boundary adapter | separate core/isaac processes already selected | no replacement evaluator or universal simulator API |
| M1/E2 MuJoCo | MuJoCo `237c17e…`, Gymnasium 1.3.0, core lock | normal MuJoCo/Gym/LeRobot seams | unchanged later PIPER-X task adapter | deferred M1 config/processors | core environment unchanged | the Isaac repin does not affect this path |

## Candidate B facts

- Isaac Lab source release line: `release/3.0.0`.
- Exact clean detached checkout: `913ac53f51b2f8d02c9e121caa4cbdd06262948e`.
- Isaac Lab distribution/source version: `16.4.0`.
- Isaac Sim: `6.0.1.0`; CPython `3.12.13`.
- torch/vision/audio `2.11.0/0.26.0/2.11.0 +cu128`; CUDA runtime `12.8`.
- `warp-lang 1.16.0`; `usd-exchange 2.3.0`; RTX 4090; LeRobot absent.
- Exact Gate C PIPER-X articulation passed initialization, reset, controlled motion,
  finite-state, one-camera, bimanual-camera, and clean-process checks.
- Candidate B native regex-batched `Camera` form produced 660/660 valid counted
  qualification frames: 220 one-camera and 440 bimanual two-camera.

## Driver conclusion

Candidate B documentation recommends the latest production driver and Linux
`580.95.05` or later. The actual kernel/user-space driver is `580.159.03`, which
satisfies that documented baseline. Candidate B also passed Kit, CUDA, PhysX,
rendering, reset, and shutdown on this host. No driver change is required.

## Frozen workspace and intentional overrides

Candidate B owns its exact `uv.lock` and `[tool.uv].override-dependencies`. The
override list is recorded verbatim in
`configs/environments/isaac_release_3_0_0.yaml`. `uv pip check` reports 11
incompatibilities, recorded verbatim in the environment manifest and compatibility
artifact. These were present during the passing Candidate B qualification; no
required S1 path failed, so they are not an S1 blocker. The S2 frozen teleop-extra
expansion then reproduced exactly the same 11 incompatibilities and no new ones;
standalone CloudXR/OpenXR, the XR Kit experience, IK/articulation, camera/reset,
and the S1 non-XR regression exercised without a required-path failure. Later
environment expansion must repeat this check.

## Runtime-scoped Isaac Teleop dependencies

`implementation.isaac_teleop` was an ambiguous historical field, not a valid
project-global pin. It has been replaced by the existing `teleop.real` and
`teleop.isaac` runtime ownership records. Gate B/core remains on
`isaacteleop==1.3.131` at `7002ed63…`; Candidate B/S2 follows Candidate B's exact
frozen teleop extra with `isaacteleop==1.4.98rc1` and its in-tree
`isaaclab_teleop==0.8.0`. The full amendment and preserved-gate analysis is recorded
in `GATE_S0_TELEOP_DEPENDENCY_AMENDMENT.md`.

## Preserved decisions

- Isaac stays in its isolated process/environment and excludes LeRobot.
- Same-process LeRobot plus Isaac is not required.
- EVAL and CONTROL are independent semantic boundaries; transports remain deferred.
- D0 policy/data semantics and the Gate C model/embodiment contract are unchanged.
- The MuJoCo selection is unchanged.
- There is no `SimulatorBackend`, `RobotBackend`, camera backend, universal sensor
  API, generic simulator registry/factory, or mandatory RPC.

## Re-acceptance

Only invalidated Isaac facts/evidence were reopened. The exact replacement pin,
environment, frozen lock/override caveat, driver baseline/observation, qualification
results, and preserved process architecture are resolved and evidenced. No
unrelated accepted gate was reopened; S0 and S1 are accepted, while S2 remains
unresolved.
