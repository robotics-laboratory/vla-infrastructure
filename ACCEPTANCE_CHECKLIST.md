# ACCEPTANCE_CHECKLIST.md

## Contract/evidence/environment consistency

- [ ] `configs/resolved_contract.yaml` is the only resolved contract.
- [ ] Every resolved static value has pinned evidence.
- [ ] Any evidence/YAML mismatch blocked the stage.
- [ ] Every runnable stage used the environment declared by its execution profile.
- [ ] No unpinned/random old environment was used as accepted evidence.
- [ ] Contract validator passes.
- [ ] Completion flags are not true while required fields remain unresolved.

## Environment reproducibility

- [ ] Exactly one `core` environment was established first.
- [ ] Core has a reproducible package/spec/lock mechanism.
- [ ] Python version is resolved.
- [ ] torch/CUDA/runtime expectations are resolved where relevant.
- [ ] Canonical launch/activation procedure is recorded.
- [ ] Manual package changes were captured in the reproducible spec.
- [ ] Every special environment has a concrete recorded conflict/vendor-runtime reason.
- [ ] No special environment exists merely for conceptual cleanliness.
- [ ] Same-process components were not split across environments without an explicitly resolved architecture/process boundary.
- [ ] Execution profile -> environment mapping is complete for each accepted stage.

## PIPER-X / driver / firmware

- [ ] Candidate evidence matrix includes environment compatibility.
- [ ] Explicit PIPER-X support checked.
- [ ] Bimanual support checked.
- [ ] Driver backend resolved rather than hard-coded.
- [ ] Firmware/profile represented per arm.
- [ ] action/observation features captured literally.
- [ ] joint order/units/gripper semantics resolved.
- [ ] URDF/frame evidence resolved.

## Quest / XR

- [ ] Exactly one process-local Isaac Teleop/CloudXR session lifecycle is used.
- [ ] Left/right streams come from that lifecycle.
- [ ] The Quest/control path runs in the environment declared for `quest_xr`.
- [ ] No custom OpenXR stack exists.
- [ ] No accidental environment split introduced RPC into the core control path.

## Dataset/action pipeline

- [ ] LeRobotDataset v3 is used directly.
- [ ] HIL merge precedes deterministic label processors.
- [ ] `dataset.action == dataset_action`.
- [ ] Residual Robot/driver/device changes are downstream and diagnosable.

## HIL

- [ ] Pinned upstream inspected first.
- [ ] Only remaining per-arm gap implemented.
- [ ] generation id bound at inference dispatch.
- [ ] old-generation result cannot enter execution queue/interpolator.
- [ ] HIL runs from the declared execution environment.

## Safety/hardware

- [ ] Safety clock domain explicit.
- [ ] Stale behavior resolved.
- [ ] Low-level fail-safe verified before autonomous hardware.
- [ ] Simultaneous bimanual operation has collision handling OR disjoint workspaces.
- [ ] Motion was never accepted from an undeclared environment.

## Simulation/benchmark

- [ ] No universal simulator backend exists.
- [ ] Simulator-specific environment exists only if justified.
- [ ] RoboTwin uses pinned native LeRobot integration.
- [ ] RoboTwin contract smoke tests run before score interpretation.

## Scope/reuse

- [ ] No generic environment manager/package resolver was built.
- [ ] No duplicate Robot/backend/dataset/runtime framework was added.
- [ ] Large integration code triggered reuse re-audit.

## Completion report

- [ ] `REUSED`
- [ ] `PINNED / VERIFIED`
- [ ] `ENVIRONMENT`
- [ ] `CONTRACT CHANGES`
- [ ] `NEW CODE`
- [ ] `NOT IMPLEMENTED`
- [ ] `TESTS`
- [ ] `RISKS / UNVERIFIED`
