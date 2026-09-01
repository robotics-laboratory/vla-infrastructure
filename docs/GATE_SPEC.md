# GATE_SPEC.md

`../configs/gate_rules.yaml` is the machine DAG. This file is the human-readable standalone definition.

## [[gate:M0]] Baseline / migration

Fresh project: establish v5.2 baseline. Migrated project: inventory old facts/evidence, preserve or explicitly invalidate them, normalize aliases and finish migration before Final RC.

## [[gate:E0]] Core environment

Resolve reproducible `core`, lock/spec, launch procedure and test/lint/type-check workflow. No robotics implementation.

## [[gate:A]] PIPER-X static/driver contract

Pin LeRobot, PIPER-X plugin, AgileX driver, exact command API/control mode and structured action/observation semantics. No hardware motion.

## [[gate:B]] Real Quest/XR contract

Use pinned NVIDIA Isaac Teleop/LeRobot path. Human acceptance covers physical left/right identity, coherent XR session ownership, controls, tracking loss, reconnect and shutdown. No robot motion required.

## [[gate:C]] Authoritative embodiment/model

Pin PIPER-X model, frames, joint semantics, calibration interface and offline FK/IK/reference checks.

## [[gate:D0]] Canonical policy/data semantics

Resolve policy-facing action/state/camera contract, feature classifications, temporal `obs_t/action_t` semantics, FPS/resampling and causality regression test.

## [[gate:S0]] Simulator/evaluation upstream audit

Pin minimum current Isaac Lab/XR/Recorder path, automated generation path, LeRobot/EnvHub eval seam, MuJoCo/Gym eval seam and PIPER-X adaptation strategy. No universal backend.

## [[gate:S1]] Isaac PIPER-X environment

Headless reset/step, asset, cameras, control semantics, processors, task success/termination and executable embodiment parity.

## [[gate:S2]] Quest -> Isaac

Physical Quest controls simulated bimanual PIPER-X. Validate axes, rotation, scale, clutch/rebase, gripper and tracking behavior, not merely left/right identity.

## [[gate:D1]] Isaac human-VR dataset

Record successful Isaac human-VR episode, explicitly map native fields to `obs_t`, `action_t`, outcome/termination, and finalize a LeRobotDataset v3 source dataset.

## [[gate:G1]] Isaac automated dataset

Generate successful episodes without per-step human control. Preserve attempts/success/failure, generator config/seeds and source-demo lineage where applicable.

## [[gate:D2a]] Isaac human <-> automated parity

Compare common training view of Isaac human-VR and Isaac automated datasets.

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

After real XR and real safety gates, enforce the resolved maximum XR pose age at the timestamped teleop-to-robot-control boundary, then record/finalize a representative real human-VR LeRobotDataset v3 source dataset.

## [[gate:D2b]] Real <-> Isaac training parity

Compare real human-VR, Isaac human-VR and Isaac automated common training view.

## [[gate:DM]] Mixed-source dataset materialization

Deterministically project selected source datasets to one identical schema and materialize final training dataset.

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
