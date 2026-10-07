# MuJoCo Quest physical run 7 — partial / M1 remains reopened

Date: 2026-09-25

Profile under test: `piperx_mujoco_quest_teleop_v9` / M1 plant v7

Operator result:

- both arms worked well;
- both grippers closed well;
- a grasped cube was not held statically and the fingers visibly wobbled.

The retained output also showed that the short regression invocation stopped
after `18 passed, 1 failed`: the test still expected profile v8 while the
runtime correctly reported v9. That stale assertion is fixed in v10, but no v10
test result is claimed here.

## Diagnostic finding

The command path was correct: each requested aperture was expanded to equal and
opposite physical-finger targets. Under contact, however, the fully independent
fingers diverged. Samples in the operator log showed symmetry error above
`25 mm`, tracking error above `50 mm`, and persistent one-sided `10 N` force
limiting. The final counters reached `612` gripper-force saturation frames.

This distinguishes the defect from insufficient trigger response or an arm-IK
problem. Raising force again would increase contact fighting without fixing the
moving grasp center.

## Narrow repair selected

The first M1 v8 / Quest v10 candidate retained both direct physical-finger
actuators and added one explicit physical relation `q1=-q2`. The operator-run
focused suite then passed 36 checks but showed that its overly stiff solver
parameters lost cube contact in the dynamic-grasp regression. M1 v9 / Quest
v11 keeps the same narrow relation with the previously stable MuJoCo constraint
reference. It does not restore the removed compatibility-joint actuator or the
old leader/follower constraint plant. The 10 N per-finger limit is unchanged.

## Acceptance state

This run is evidence that v9 is not acceptable for cube retention. It is not
acceptance evidence for v11. M1 remains `GATE_M1_REVALIDATION_REQUIRED` pending
the operator-run focused regression, physical Quest grasp check, and the full
NVIDIA EGL verifier.
