# MuJoCo Quest physical run 3 — failed/remediation input

Date: 2026-09-22

Status: operator feedback identified remaining presentation, sensitivity,
gripper, and shutdown failures in `piperx_mujoco_quest_teleop_v4`. This report
is remediation input, not a completed human acceptance worksheet or accepted
evidence object. It does not accept the additive profile, alter accepted M1, or
start E2. No CAN or physical PIPER-X interface was in scope.

## Retained observations

- Both arms remained much too sensitive.
- At VR entry the three camera panels appeared much too high.
- A strangely shaped surrounding region/boundary was visible with the camera
  panels inside it.
- The operator requested an audit of whether program joint order/signs match
  the robot model.
- Both grippers again appeared to close continuously and did not respond
  normally to the intended trigger close command.
- Shutdown raised `EGL_NOT_INITIALIZED` from MuJoCo
  `Renderer.close -> GLContext.free -> eglDestroyContext`, followed by repeated
  ignored exceptions from `Renderer.__del__` and `GLContext.__del__`.

Only the supplied traceback excerpt is retained in this repository report; a
complete stdout path and hash were not supplied, so this is not registered as a
passing or complete physical human-gate evidence object.

## Code-backed findings

1. V4 deliberately selected unit translation/rotation gain. Its synthetic
   accumulated-gain test confirms approximately one-to-one TCP/controller
   displacement; the new physical observation establishes that this is still
   too sensitive as an operator profile even though it is mathematically
   coherent.
2. V4 used absolute OpenXR stage positions with fixed Y coordinates. Their
   perceived height therefore depended on the Quest floor/stage calibration
   instead of the operator's current head pose.
3. V4 cleared the complete Televiz XR projection layer to opaque dark gray
   (`alpha=1`). The pinned runtime advertises `ALPHA_BLEND` passthrough, so the
   opaque clear can expose the projection-layer outline as the observed
   surrounding region.
4. The requested joint audit found no mismatch to repair. Both LeRobot
   `RobotKinematics` instances use `joint1..joint6`; the Quest D0 output is
   left J1..J6/gripper followed by right J1..J6/gripper; and the MuJoCo
   actuator slots target the correspondingly namespaced joints in exactly that
   order with positive degree-to-radian scale. This agrees with the accepted
   Gate C/M1 FK, limit, and positive-direction parity evidence.
5. The tuned Quest-only gripper plant remains bounded and monotonic in
   automated direct and slew tests, so the new report does not justify changing
   the accepted M1 XML or replacing the servo again. V4 did, however, allow the
   same trigger press used to click WebXR Play to become a close command on the
   first active frames. The incomplete stdout prevents claiming this is the
   sole cause of the observed behavior.
6. Catching a late `env.close()` exception prevents it from aborting later
   owners, but MuJoCo 3.9.0 retains its EGL handle when `eglDestroyContext`
   raises. Python destructors then retry that invalid handle, producing the two
   additional ignored exceptions in the supplied traceback.

## V5 remediation requiring physical validation

- Reduce normal translation/rotation gain to `0.5` and precise gain to
  `0.125`, preserving the four-to-one ratio.
- Capture one valid HMD pose at startup; compose configured head-relative
  panel offsets/orientations into stage space and keep the resulting panels
  world-stable.
- Use transparent Televiz clear (`RGBA 0,0,0,0`) so upstream `ALPHA_BLEND`
  preserves passthrough outside the panels.
- Preserve the verified Gate C/D0/M1 joint order and signs; retain the new
  Quest-edge regression so later changes cannot silently permute them.
- After every Play, reset, or tracking recovery, hold each gripper until its
  trigger has been released to at least `95 mm` open intent. The release sample
  only arms that side; subsequent trigger commands keep the existing
  `10 mm/control tick` slew and instance-only stable servo tuning.
- Close MuJoCo EGL while the graphics-bound `TeleopSession` is still alive,
  before session/panel/CloudXR destruction. If upstream EGL destruction has
  already failed, clear its invalid ownership handles to prevent destructor
  retries while still recording the teardown failure.

Profile `piperx_mujoco_quest_teleop_v5` remains
`CONFIGURED_PHYSICAL_QUEST_VALIDATION_REQUIRED` until every line of the updated
physical worksheet passes with retained stdout.
