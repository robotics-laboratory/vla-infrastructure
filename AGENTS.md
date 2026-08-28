# AGENTS.md

## 1. Binding model

The implementation must agree with all three:

```text
pinned upstream evidence
configs/resolved_contract.yaml
the environment actually used to execute the stage
```

Rules:

1. `configs/resolved_contract.yaml` is the only resolved runtime/environment contract.
2. Every resolved value must be backed by pinned evidence or hardware validation as required.
3. If pinned evidence and YAML disagree, STOP and re-resolve.
4. If the active environment disagrees with the environment declared for the stage, STOP. Do not continue from a convenient old environment.
5. Do not use unpinned `main/latest` behavior after a contract is resolved.
6. Topic docs define procedures/invariants, not additional resolved facts.

Procedure order:

```text
AGENTS.md
→ topic-specific document
→ IMPLEMENTATION_PLAN.md
→ README.md
```

`ACCEPTANCE_CHECKLIST.md` is a review gate.

---

## 2. Mission

This is an integration project, not a robotics framework or environment-orchestration project.

Build the required system with the minimum necessary custom production code while preserving real data, HIL, safety and reproducibility invariants.

---

## 3. Reuse ladder

```text
1. upstream already does it -> use it
2. config is enough -> configure it
3. composition is enough -> compose it
4. one missing translation -> thin adapter
5. official extension point -> extend it
6. local replacement against an existing public boundary -> implement it
7. upstream fork -> last resort
```

Never start at step 6.

---

## 4. Required upstream reuse audit

Before non-trivial code:

```text
UPSTREAM REUSE AUDIT

Pinned component(s):
- ...

What already exists:
- ...

Exact remaining gap:
- ...

Smallest implementation:
- ...

Evidence:
- repo / commit / path / symbol or section

Environment impact:
- core-compatible | conflict discovered | vendor runtime required
- exact evidence for any separation

Why no new framework/base class is needed:
- ...
```

If the gap or environment conflict is vague, inspect upstream again.

---

## 5. Environment rule

Read `ENVIRONMENT_POLICY.md`.

Default:

```text
ONE reproducible core environment
```

Do not create `isaac-env`, `robotwin-env`, `sim-env`, etc. merely because those names are convenient.

A special environment requires a recorded reason and reproducible lock/manifest.

If two components must share a process, especially the Quest/Isaac Teleop + control path, do not split them into separate environments without an explicitly resolved process boundary that preserves all relevant invariants.

Manual package installation that is not captured by the selected environment specification is not accepted as reproducible setup.

---

## 6. Forbidden by default

Unless a concrete remaining gap survives the reuse audit, do not create:

- custom `RobotAction`
- custom `RobotObservation`
- custom `TeleopIntent`
- global `RobotBackend`
- `BackendDescription`
- generic backend registry/factory
- custom recorder/dataset/replay/rollout framework
- replacement DAgger runtime
- custom IK/FK solver
- custom OpenXR/controller stack
- custom video transport
- universal simulator backend/API
- generic ActionMux
- mandatory RPC/process separation
- mandatory Docker service per component
- environment manager abstraction
- custom package resolver
- one Python environment per conceptual subsystem
- project-wide radians/gripper normalization solely for neatness
- project-wide action ontology when LeRobot processor/Robot contracts suffice

Do not add empty "future extensibility" scaffolding.

---

## 7. Resolved contract

Resolve only in `configs/resolved_contract.yaml`:

```text
Robot/plugin/driver pins
PIPER-X firmware/profile
action/observation contract
URDF/model/frames
CAN/calibration
processor sequence
safety/timing
environment ownership
environment locks/manifests
execution profile -> environment mapping
```

Large lock/calibration/model artifacts may live separately but must be referenced by exact path and SHA-256 when appropriate.

Run:

```bash
python tools/validate_resolved_contract.py configs/resolved_contract.yaml
```

before claiming a gate complete.

---

## 8. Baseline ownership/path

```text
Quest XR
↓
ONE process-local Isaac Teleop/CloudXR lifecycle
↓
left + right controller streams
↓
LeRobot official Isaac Teleop integration pattern
↓
resolved PIPER-X data/action path
↓
LeRobot dataset / Robot/send path
↓
selected Robot plugin
↓
selected AgileX driver
↓
hardware
```

The environment declared for this process must contain every in-process dependency required by this path.

---

## 9. Action-label invariant

Use `SAFETY_TIMING.md` terminology:

```text
data_action
→ deterministic label processors
→ dataset_action
→ Robot.send_action()
→ residual device safety
→ device_accepted_command
```

HIL merge occurs before deterministic label processors.

`dataset.action == dataset_action`, not automatically physical execution.

---

## 10. Topic ownership

- environment/version/CUDA/launch ownership -> `ENVIRONMENT_POLICY.md`
- PIPER-X/driver/firmware -> `PIPER_X_VERIFICATION.md`
- HIL/concurrency -> `HIL_EXTENSION.md`
- safety/timing/action labels/inter-arm -> `SAFETY_TIMING.md`
- simulators/process isolation/RoboTwin -> `SIMULATION_POLICY.md`

---

## 11. Numerical criteria

Unknown hardware values remain `DECIDE/PIN`.

Codex must not fabricate safety thresholds, timeouts, workspace boundaries or physical behavior.

---

## 12. Code-size discipline

Soft reuse re-audit triggers:

```text
>300 LOC in one new integration module
>1000 LOC new runtime code for one integration stage
```

Tests and environment validation scripts are excluded.

---

## 13. Completion report

```text
REUSED
- ...

PINNED / VERIFIED
- ...

ENVIRONMENT
- environment id used
- lock/manifest
- reason for any special environment
- launch command/profile

CONTRACT CHANGES
- ...

NEW CODE
- ...

NOT IMPLEMENTED
- delegated to upstream

TESTS
- ...

RISKS / UNVERIFIED
- ...
```
