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

## Exact fail-open gaps closed

The local adapter previously accepted the SDK's uninitialized zero-valued telemetry envelopes, substituted zero for absent joint or gripper fields, ignored partial six-joint commands while continuing with a gripper command, and could send the left arm before discovering an invalid numeric value on the right. It also treated an enable timeout as a warning, exposed no configured/enabled/motion-ready distinction, left resources acquired by partial camera or bimanual connection attempts, and could refuse or stop cleanup in partial/disconnect-error states.

## Processor / config / adapter required

Only the existing `PiperXFollower` and `BiPiperXFollower` adapter classes require changes. The adapter requires positive finite SDK envelope timestamps and rates before accepting telemetry, rejects incomplete telemetry and partial/invalid arm actions, tracks connected/configured/enabled/motion-ready state, fails and rolls back an enable timeout, converts both bimanual actions before either is sent, rolls back attempted camera and bimanual connects, and cleans every acquired resource on partial or failing disconnect. Version 0.2.2 also extends the pinned SDK parser without replacing it, atomically copying all required joint-pair/gripper values, per-component SocketCAN receive timestamps, and identities for temporal recording. No label processor, dataset action schema, command units, joint ordering, or configuration key changes are required.

Version 0.2.2 also checks the wall-to-monotonic offset on every temporal observation;
a realtime clock step or excessive drift fails closed rather than making CAN feedback
appear artificially fresh or future-dated.

## Environment impact

No external dependency changes. The core environment, Python version, LeRobot pin, SDK pin, and execution-profile boundaries are unchanged; the editable package and lock entry advance to 0.2.2. Verification is offline with the existing fake SDK plus construction of the actual pinned SDK subclass; no CAN device or physical robot is accessed.

The hardened adapter is selected by the v5.2.5 resolved contract through its exact implementation commit and `adapter_fail_closed` semantics. Gate A is reopened for the confirmed safety defect and re-accepted with the audit plus focused fake-SDK regression evidence. This does not reopen or accept a hardware gate.

## Why no project framework is needed

The defects are local lifecycle and validation obligations at the existing hardware edge. Small state flags and cleanup/validation helpers in the concrete PIPER-X classes close the gap without a robot backend, registry, RPC layer, or replacement recorder.
