# MuJoCo Quest physical run 9 — failed / profile v20 required

Date: 2026-09-28  
Profile exercised: `piperx_mujoco_quest_teleop_v19`  
Result: `FAILED_PHYSICAL_VALIDATION`

Raw operator log:

- source: Codex attachment `Pasted text.txt`
- SHA-256: `dedfdb43b962e0dd1e0adf071c4c9d485be239b6598e8f7c5d272fb380d8f889`

## Operator observations

- both arms moved well;
- the cube was initially clamped;
- after contact the gripper began jerking and could not retain the cube.

## Log-derived diagnosis

The arm path was healthy: there were zero IK failures and zero Cartesian
saturations. Maximum joint target errors were comparable at `12.675 degrees`
left and `14.347 degrees` right.

The failure was isolated to contact transients in the gripper. During a right
grasp with a constant `0 mm` target, measured aperture moved from approximately
`23.462 mm` to `37.100 mm`; maximum right symmetry error reached `8.286 mm`.
At an earlier partial-close target of `22.161 mm`, one right actuator reached
the v19 `-12 N` opening-direction limit. Thus the extra opening reserve added
for released-gripper stability remained available to the velocity/position
servo during contact rebound and could oppose the retained 8 N closing path.

The run completed 1092 control steps with four explicit resets. Final counters
were 173 gripper-slew and 298 gripper-force saturation frames, with no teardown
failure reported in the supplied output.

## Narrow remediation

Profile v20 keeps all arm, IK, D0, equality, pad, friction, gain, damping, and
closing-force settings. It changes only when the v19 opening reserve is active:

- accepted target `>=95 mm`: mirrored 12 N opening reserve;
- accepted target `<95 mm`: symmetric `[-8, +8] N` on both finger actuators.

This prevents partial/closed contact rebound from invoking 12 N while retaining
the stronger fully-open hold. Focused automated and physical evidence are
required; this document is not acceptance evidence.
