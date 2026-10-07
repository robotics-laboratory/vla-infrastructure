# MuJoCo Quest physical run 4 — failed/partial

Date: 2026-09-24

Profile exercised: `piperx_mujoco_quest_teleop_v5`

Status: `FAILED/PARTIAL`. This observation is remediation input, not acceptance evidence. The
stdout was supplied inline by the operator and was not retained as a separately hashable raw file.

## Passed observations

- Normal and precise controller sensitivity felt usable.
- The simulated joint mapping appeared to match the intended physical joints.
- The 1800-step run completed with `teardown_failures: []`.
- Trigger telemetry and commanded target polarity were correct: `trigger=0` requested `100 mm`
  open and `trigger=1` requested `0 mm` closed.

## Failed observations

- Grippers appeared to close without an operator command and could not reliably retain a cube.
- Wrist-camera panels showed an arm joint instead of the workspace in front of each gripper.

## Log-derived diagnosis

The command path was not issuing an uncommanded close. With `trigger=0`, the target remained
`100 mm`, but the measured leader aperture repeatedly fell to roughly `77–90 mm` during arm
motion. Full trigger presses correctly produced `0 mm` targets. This isolated the failure to the
simulated gripper plant/contact coupling rather than trigger polarity or routing.

The task MJCF also declared the wrist camera with local `-Z` optical direction while the gripper
approach direction is local `+Z`, explaining the joint-dominated view.

## Remediation selected

- Reverse both wrist-camera optical axes to gripper `+Z` and verify a marker on that axis renders
  at image center.
- Disable collision on the tapered imported finger visuals and add fixed flat fingertip contact
  pads matching the real grasping faces.
- Stiffen the leader/follower equality constraints and use the revalidated M1 gripper servo
  (`kp=125`, `kv=40`, `5 N`, leader armature `0.1 kg`, damping `2 N s/m`).
- Add per-side follower aperture, mimic error, actuator force, and force-limit diagnostics.

The remediated profile is `piperx_mujoco_quest_teleop_v6` and still requires a new physical Quest
acceptance run.
