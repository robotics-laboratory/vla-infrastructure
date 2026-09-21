# GATE_SPEC.md

`../configs/gate_rules.yaml` is the machine DAG. This file is the human-readable standalone definition.

## [[gate:M0]] Baseline / migration

Fresh project: establish v5.2 baseline. Migrated project: inventory old facts/evidence, preserve or explicitly invalidate them, normalize aliases and finish migration before Final RC.

## [[gate:E0]] Core environment

Resolve reproducible `core`, lock/spec, launch procedure and test/lint/type-check workflow. No robotics implementation.

## [[gate:A]] PIPER-X static/driver contract

Pin LeRobot, PIPER-X plugin, AgileX driver, exact command API/control mode and structured action/observation semantics. Prove fail-closed telemetry, complete arm-action, readiness, enable-timeout, and bimanual lifecycle behavior offline. No hardware motion.

## [[gate:B]] Real Quest/XR contract

Use pinned NVIDIA Isaac Teleop/LeRobot path. Human acceptance covers physical left/right identity, coherent XR session ownership, controls, tracking loss, reconnect and shutdown. No robot motion required.

## [[gate:C]] Authoritative embodiment/model

Pin PIPER-X model, frames, joint semantics, calibration interface and offline FK/IK/reference checks.

## [[gate:D0]] Canonical policy/data semantics

Resolve the v4 three-camera ordered canonical schema and fingerprint, unchanged
PIPER-X action/state units/order, common immutable causal transactions and explicit
Isaac-human, Isaac-automated and real-physical profiles. Offline evidence must
exercise prepare/complete/commit/abort, payload binding, epochs, duplicate rejection,
physical timing preservation and profile isolation. Reaccept D0 atomically with
its new evidence; historical proof remains frozen. This does not qualify runtime
camera/XR/recording bindings or change S0/S1 facts.

## [[gate:S0]] Simulator/evaluation upstream audit

Pin minimum current Isaac Lab/XR/Recorder path, automated generation path, LeRobot/EnvHub eval seam, MuJoCo/Gym eval seam and PIPER-X adaptation strategy. No universal backend.

## [[gate:S1]] Isaac PIPER-X environment

Headless reset/step, asset, cameras, control semantics, processors, task success/termination and executable embodiment parity.

## [[gate:S2]] Quest -> Isaac

Physical Quest controls simulated bimanual PIPER-X. Validate axes, rotation, scale, clutch/rebase, gripper and tracking behavior, not merely left/right identity.

The current physical acceptance target is `./run-vr` in run mode under
[[profile:isaac_vr]], with the composition selected by `configs/isaac61_vr_runtime.yaml`.
`./run-vr diag` qualifies that same implementation with additional observers.
See the [operator guide](project/RUN_VR_OPERATIONS.md) and
[current human worksheet](project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md).
Runtime smoke PASS does not accept S2. The optional asset lab remains experimental
and cannot claim S2 acceptance. Registered human evidence and all machine
requirements remain mandatory.

## [[gate:D1]] Isaac human-VR dataset

Record successful Isaac human-VR episodes using the Isaac human causal profile.
Require registered proof for the three-camera capture barrier, resolved XR identity,
post-DifferentialIK preclip action seam, native recorder mapping, converter,
causal transition/successor, dataset manifest and demonstration-quality envelope.
Commit after successful transition plus successor observation. Physical XR/camera
acquisition-age paths are not D1 prerequisites. Finalize a LeRobotDataset v3 source.

## [[gate:G1]] Isaac automated dataset

Generate successful episodes with the Isaac automated causal profile, three-camera
barrier and completed transition/successor. Preserve attempts/success/failure,
generator decision/revision/state/seeds and source-demo lineage where applicable;
no synthetic XR fields or physical acquisition timestamps.

## [[gate:D2a]] Isaac human <-> automated parity

Compare the full three-camera canonical schema/fingerprint and profile-appropriate causal proof of Isaac human-VR and Isaac automated datasets.

## [[gate:M1]] MuJoCo PIPER-X environment

Minimal PIPER-X Gym/LeRobot environment with explicit control/timestep/processors/task semantics and embodiment parity.

## [[gate:E1]] Isaac evaluation

Run actual policy evaluation and retain full run manifest/result.

## [[gate:E2]] MuJoCo evaluation

Run actual policy evaluation and retain full run manifest/result.

## [[gate:E3]] Cross-sim evaluation

Require E1/E2, same checkpoint SHA, same policy contract revision, same canonical task id/revision and parity report. Equal scores are not required.

## [[gate:R0]] Hardware read-only

For both arms prove device/CAN identity, actual firmware, driver profile, robot variant, command API/control mode. No motion.

## [[gate:R1]] One-arm hardware validation

One arm at a time: joint sign/scale, gripper polarity/range, clipping/slew, accepted-command behavior and low-level fail-safe. Explicit human authorization per motion test.

## [[gate:R1B]] Bimanual real safety

Prove collision handling or disjoint workspaces and preserve left/right identity/workspace evidence.

## [[gate:R2]] Real human-VR dataset

After real XR and real safety gates, enforce the resolved maximum XR pose age at the timestamped teleop-to-robot-control boundary, retain strict state/action/camera/XR age, clock/sequence and skew requirements,
including scene-camera acquisition, then record/finalize a representative real
human-VR LeRobotDataset v3 source with complete causal transition proof.

## [[gate:D2b]] Real <-> Isaac training parity

Compare the full three-camera schema/fingerprint and declared profiles of real human-VR, Isaac human-VR and Isaac automated datasets; retain physical timing on the real source.

## [[gate:DM]] Mixed-source dataset materialization

Deterministically project selected source datasets to one identical schema and materialize final training dataset, preserving three-camera schema/profile parity and full stream validation.

## [[gate:DQ]] Dataset QA / semantic replay

Full-read every frame/video stream, DataLoader smoke, transition inspection, QA report and semantic replay where applicable.

## [[gate:T0]] Training compatibility smoke

Conditionally mandatory only when `training_ready_claim=true`. Tiny optimization/checkpoint save+load/inference smoke; this is compatibility evidence, not quality evaluation.

## [[gate:HIL]] Per-arm HIL

Resolve mixed-mode semantics, generation invalidation, takeover/release and physical intervention evidence. Enforce the resolved maximum XR pose age at the timestamped human-teleop-to-robot-control boundary.

## [[gate:R3]] Real policy rollout

Requires real safety, HIL if required and simulator evaluation. Pin checkpoint/processors/task. Use bounded speed/workspace, reachable E-stop, explicit human authorization, start/stop procedure and retained evidence.

## [[gate:B0]] Benchmark integration readiness

Conditionally mandatory when benchmark-native architecture is required. Prove profile/processors/result-artifact mechanism without claiming a selected benchmark run.

## [[gate:B1]] Selected benchmark run

Conditionally mandatory only when a concrete benchmark is selected. Preserve official upstream protocol.
