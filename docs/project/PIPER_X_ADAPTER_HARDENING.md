# PIPER-X Adapter Hardening Audit

## Capability / gate

Pre-hardware hardening of the real single-arm and bimanual PIPER-X LeRobot adapter. This changes no gate state and supplies no physical evidence for R0, R1, R1B, R2, HIL, or R3.

## Pinned upstream candidates

- LeRobot 0.6.1 at `7e241bd630a3719a56157a497ce5d08f244784f1`.
- `piper-sdk` 0.6.1 at `081e7c588e5b79eeaefa67a0469bcc701c81014f`.
- Evo-RL donor at `6f2db449a21e1bac750b996f2e27cac6739aa63f`.

These are the existing Gate A pins; this task does not select or repin an upstream dependency.

## What upstream already owns

LeRobot owns the `Robot` lifecycle and feature/action interfaces, processors, recorder loop, and dataset writer. `piper-sdk` owns CAN transport, PIPER enable/disable, telemetry messages, J-position `JointCtrl`, and `GripperCtrl`. The donor establishes the thin single-arm and process-local bimanual composition used by the project plugin.

## Exact remaining gap

The local adapter previously substituted zero for absent joint or gripper telemetry, ignored partial six-joint commands while continuing with a gripper command, treated an enable timeout as a warning, exposed no configured/enabled/motion-ready distinction, left the first arm connected after a second-arm connect failure, and stopped bimanual disconnect after the first cleanup error.

## Processor / config / adapter required

Only the existing `PiperXFollower` and `BiPiperXFollower` adapter classes require changes. The adapter rejects incomplete telemetry and partial arm actions, tracks connected/configured/enabled/motion-ready state, fails and rolls back an enable timeout, prevalidates both bimanual actions before either is sent, rolls back bimanual connect, and attempts cleanup of both arms on disconnect. No label processor, dataset schema, command units, joint ordering, or configuration key changes are required.

## Environment impact

None. The core environment, Python version, LeRobot pin, SDK pin, lockfile, and execution-profile boundaries are unchanged. Verification is offline with the existing fake SDK; no CAN device or physical robot is accessed.

The hardened adapter is selected by the v5.2.4 resolved contract through its exact implementation commit and `adapter_fail_closed` semantics. Gate A is reopened for the confirmed safety defect and re-accepted with the audit plus focused fake-SDK regression evidence. This does not reopen or accept a hardware gate.

## Why no project framework is needed

The defects are local lifecycle and validation obligations at the existing hardware edge. Small state flags and cleanup/validation helpers in the concrete PIPER-X classes close the gap without a robot backend, registry, RPC layer, or replacement recorder.
