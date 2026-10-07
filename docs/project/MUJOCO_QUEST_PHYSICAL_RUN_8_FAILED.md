# MuJoCo Quest physical run 8 — failed / profile v19 required

Date: 2026-09-28  
Profile exercised: `piperx_mujoco_quest_teleop_v18`  
Result: `FAILED_PHYSICAL_VALIDATION`

Raw operator log:

- source: Codex attachment `Pasted text.txt`
- SHA-256: `f2ab6a9b75f0d29e99ac9de8acaf1b7e7c444617b52821a7ac6575b5c3f883f9`

## Operator observations

- the arms did not feel symmetric;
- the cube remained difficult to grasp.

## Log-derived diagnosis

The left/right command and IK paths remained structurally symmetric: both
controllers had 874 valid tracking frames, there were no IK failures or
Cartesian clips, and maximum target-to-measured joint errors were comparable
at `25.000 degrees` left and `24.125 degrees` right.

The physical fingers were not equally stable across poses. With both targets
at `100 mm`, the left aperture fell to `46.480 mm` in one pose and the right
aperture fell to `9.814 mm` in another. The affected finger actuators reached
their `8 N` opening-direction limits; maximum symmetry errors were `14.288 mm`
left and `8.264 mm` right. The side exhibiting the failure changed during the
same run, which rules out a fixed left/right mapping error and isolates the
perceived asymmetry to load-dependent gripper compliance.

During explicit close attempts, an aperture near the 40 mm cube width was
observed while the existing closing limit was active. Earlier coupled-finger
experiments also showed that raising closing force to 10 or 12 N caused earlier
loss/ejection in the retained wrist-motion regression. Closing force therefore
must not be raised again merely to fix commanded-open collapse.

The explicit reset was correct: both arms returned to the canonical home joints
and both grippers to `50 mm`. The later right target near `9.06 mm` followed an
intentional trigger press and was safely held after tracking became invalid.

## Narrow remediation

Profile v19 keeps the existing symmetric IK, D0 mapping, `q1=-q2` relation,
contact model, and 8 N closing force. It changes only the mirrored opening
reserve:

- joint 1 force range: `[-8, +12] N`;
- joint 2 force range: `[-12, +8] N`.

This gives both physical fingers the same 12 N outward authority without
increasing the force that clamps or ejects a cube. Focused automated tests and
a new physical Quest run are required; this document is not acceptance evidence.
