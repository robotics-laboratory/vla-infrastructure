# MuJoCo Quest physical run 2 — partial/remediation input

Date: 2026-09-21

Status: operator feedback identified two remaining motion-quality failures in
`piperx_mujoco_quest_teleop_v3`. This report is remediation input, not a
completed human acceptance worksheet. It does not accept the additive profile,
M1, or E2. No CAN or physical PIPER interface was used.

## Physical observations

- Arm kinematics responded much too strongly to small controller movements,
  as if controller sensitivity were amplified.
- Each gripper now followed its trigger in the correct direction and no longer
  exhibited the previous autonomous open/close limit cycle, but its full travel
  was too slow for comfortable teleoperation.

## Isaac comparison and exact remaining gap

Both profiles reuse upstream `Se3RelRetargeter` with position and rotation
smoothing `alpha=0.5`. Isaac S2 applies its relative IK command against the
currently measured TCP and retains separately selected `2.0` normal / `0.5`
precise gains. The corrected MuJoCo edge instead integrates every filtered
delta, including the decaying smoothing tail, into a persistent actuator
target. With gain `2.0`, the accumulated MuJoCo target therefore moves roughly
twice the physical controller displacement. This is a runtime-edge tuning
difference, not a reason to replace upstream retargeting or create a shared
teleoperation framework.

The v3 gripper edge additionally limited its target to `2 mm` per 30 Hz control
tick. Endpoint-to-endpoint simulation measured about `2.10 s` to reach within
`2 mm` of the requested aperture. The already introduced instance-only stable
servo remained bounded and monotonic under a direct full step, showing that
the old conservative software slew was now the dominant avoidable delay.

## v4 remediation requiring physical validation

- Set normal translation/rotation gain to `1.0` for approximately one-to-one
  accumulated controller motion.
- Set precise translation/rotation gain to `0.25`, preserving the existing
  four-to-one normal/precise ratio.
- Raise the bounded gripper target slew to `10 mm/control tick`. Automated
  endpoint-to-endpoint simulation reaches within `2 mm` in about `1.07 s`,
  stays inside `[0, 100] mm`, and remains monotonic.
- Keep the upstream controller graph, M1 environment/XML, Quest-only actuator
  tuning, persistent IK target, D0 units, saturation reporting, and lifecycle
  unchanged.

Profile `piperx_mujoco_quest_teleop_v4` remains
`CONFIGURED_PHYSICAL_QUEST_VALIDATION_REQUIRED` until its worksheet is
completed.
