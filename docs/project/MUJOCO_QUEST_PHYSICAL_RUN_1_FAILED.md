# MuJoCo Quest physical run 1 — failed/diagnostic

Date: 2026-09-21

Status: physical run reached the Quest/MuJoCo control loop, but human motion
quality failed. This artifact does not accept the additive profile, M1, or E2.
No CAN or physical PIPER interface was used.

## Retained input

The operator supplied a 247-line stdout capture through the Codex attachment
store. Its SHA-256 is
`0ae96207f8adeb8e736251e391658077071f4eddd7f3a5e742dd51cc5553e032`.
The attachment path is session-local and is not treated as a durable repository
artifact; this document retains the findings needed for the next run.

## What worked

- CloudXR/OpenXR connected to the physical Quest.
- The WebXR session stayed STOPPED before Play and entered RUNNING after Play.
- Both controller branches reported valid tracking for a substantial interval.
- The MuJoCo loop had no reported IK failures or control-loop overruns.

## Human failures

- Cartesian arm response did not correspond well to controller motion.
- Wrist/orientation response was especially weak or absent.
- Both grippers appeared to open and close repeatedly without stable intent.

## Evidence-backed root causes

1. The v2 IK adapter recomputed every incremental controller command from the
   measured MuJoCo qpos. The position-controlled plant does not reach a new
   target in one 30 Hz control frame, so the following frame discarded most of
   the still-pending target. A zero controller delta immediately replaced the
   target with measured qpos. This attenuated translation and made short
   orientation commands disappear before the plant reached them.
2. The v2 edge reused Isaac's raw `[x, -z, y]` tuple even though M1 declares
   `+X` forward and `+Y` left. Under standard OpenXR axes this mapped physical
   forward motion to M1 left and physical right motion to M1 forward: a 90
   degree semantic yaw error affecting translation and rotation.
3. The v2 gripper slew limit also used measured qpos as its starting point
   instead of the last accepted actuator target. Plant lag therefore fed back
   into command generation.
4. A direct constant-target reproduction isolated an additional physical-model
   defect: the default gripper servo crossed the nominal `[0, 100] mm` range,
   oscillated from `-18.7` to `112.8 mm`, changed direction 15 times in three
   seconds, and ended near `1.27 mm` despite a constant `100 mm` target. The
   lightweight equality-constrained leader, `kp=400/kv=40`, and `2 N` force
   saturation formed a limit cycle. This directly explains autonomous repeated
   opening/closing even when the Quest trigger is steady.
5. Accepted M1 truncates at 300 policy ticks. The interactive runner interpreted
   every truncation as a reset, silently restoring home around active steps
   300, 600, and 900. The capture's synchronized `tracking_rebased` events near
   steps 601 and 900 match this automatic-reset path. Each reset also restored
   both grippers to 50 mm before the live trigger commanded them again.
6. The old aggregate `saturation_frames` counter could not distinguish
   Cartesian, joint, and gripper limiting. It rose to 729, so the run proved
   extensive limiting but could not localize it.
7. Owned CloudXR stopped before Televiz and MuJoCo EGL cleanup. The capture ends
   with IPC broken-pipe messages and `EGL_NOT_INITIALIZED` during renderer
   destruction.

## v3 remediation requiring a new physical run

- Persist and integrate from the last accepted D0 actuator target.
- Map OpenXR forward/right/up to M1 forward/right/up with `[-z, -x, y]` for
  both translation and spatial rotation vectors.
- Hold that target on zero deltas and bound target-to-measured joint error to
  15 degrees.
- Slew grippers from their last accepted target and hold on invalid/rebase.
- Apply stable Quest-only gripper actuator parameters to the runtime model
  instance (`kp=50`, `kv=10`, force `2 N`, armature `0.1 kg`, damping
  `2 N s/m`). Opening and closing regression traces are bounded to `[0, 100]`
  mm and monotonic within `0.01 mm/tick`. The accepted M1 asset is unchanged.
- Disable task-end termination only for the interactive Quest construction;
  default M1 still truncates at 300 ticks. Only explicit Reset restores home.
- Emit filtered controller translation/rotation deltas, squeeze/trigger values,
  measured and target gripper aperture, target error, and separate Cartesian,
  joint, and gripper saturation counters every 30 session frames.
- Close TeleopSession, panels, and MuJoCo EGL resources before owned CloudXR.

Automated regressions cover these mechanics, including all three Placo rotation
axes, but cannot establish physical signs, comfort, or controller fidelity.
Profile `piperx_mujoco_quest_teleop_v3` remains
`CONFIGURED_PHYSICAL_QUEST_VALIDATION_REQUIRED`.
