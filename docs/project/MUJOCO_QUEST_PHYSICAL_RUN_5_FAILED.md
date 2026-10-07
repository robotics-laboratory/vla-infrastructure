# MuJoCo Quest physical run 5 — failed/partial

Date: 2026-09-24

Profile exercised: `piperx_mujoco_quest_teleop_v6`

Status: `FAILED/PARTIAL`. This observation is remediation input, not acceptance evidence.

Raw operator log:

- source: Codex attachment `Pasted text.txt`
- SHA-256: `8bf7f32009b5175655db614ae6ac8fd62b5834682e51cd0d17e6e97272620606`

## Passed observations

- Gripper close response was noticeably better than the preceding run.
- Controller sensitivity was usable.
- The run did not reveal a left/right routing reversal or an unreachable canonical cube pose.

## Failed observations

- Open grippers wandered substantially while the arms moved instead of retaining a fixed aperture.
- Fine reach became difficult: the operator could not reliably reach the cube and suspected that
  some joints stopped responding or could not fully extend.

## Log-derived diagnosis

The log contains 80 status samples, 60 while RUNNING. Trigger polarity remained correct, but the
right physical finger aperture fell to `59.901 mm` against a `100 mm` target. Maximum observed
leader/follower mimic error was `18.181 mm` left and `48.338 mm` right; follower loading, not the
D0 trigger command, caused the apparent autonomous closing. Gripper saturation accumulated to
141 frames and gripper-force saturation to 40 frames.

Cartesian saturation remained zero. Joint target error nevertheless reached `13.110 degrees`
left and `14.738 degrees` right, effectively touching the former `15 degree` target-versus-plant
guard. The pinned upstream relative retargeter also used fixed `1 mm` translation and `0.01 rad`
rotation thresholds before the accepted half-scale gain, so deliberate controller motion below
about `2 mm` per control frame was discarded.

An independent LeRobot/Placo audit solved both canonical cube-center poses while preserving the
home tool orientation. The solutions stayed inside every accepted Gate C joint limit. This rules
out a scene-workspace or joint-order defect and isolates the reach failure to filtering and
plant-lag bounds.

## Remediation selected

- Preserve the physically accepted normal/precise gains (`0.5` / `0.125`) and lower only the
  Quest relative-motion deadbands to `0.25 mm` and `0.0025 rad`.
- Raise the target-versus-measured joint guard from `15` to `25 degrees`; retain the accepted joint
  limits and the `8 degree/control-tick` target step bound.
- Keep the external 14-value D0/native contract unchanged, but deterministically expand each
  aperture command inside the concrete MuJoCo environment to the leader and both follower finger
  position actuators.
- Use bounded follower parameters `kp=1500`, `kv=30`, force `5 N`, retaining the leader's
  `kp=125`, `kv=40`, force `5 N`, armature `0.1 kg`, and damping `2 N s/m`.
- Report both follower actuator forces as well as aperture, mimic error, and combined force-limit
  state.

The remediated profile is `piperx_mujoco_quest_teleop_v7`. It still requires a new physical Quest
acceptance run.
