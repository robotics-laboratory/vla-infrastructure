# MuJoCo Quest physical run 6 — failed / M1 reopened

Date: 2026-09-25  
Profile exercised: `piperx_mujoco_quest_teleop_v7`  
Result: `FAILED_PHYSICAL_VALIDATION`  
Raw runtime log: not supplied for this run

## Operator observations

- The cube still could not be grasped reliably.
- The visible gripper fingers remained in “free floating” during arm motion instead of holding a fixed commanded aperture.
- The left arm felt substantially more responsive and correct than the right arm.

These observations contradict the prior automated gripper-retention evidence. Under the normative conflict rule, M1 is reopened and remains unresolved until new automated and physical evidence is retained.

## Root-cause audit and v8 remediation

The v7 plant simultaneously applied a position actuator to a compatibility aperture joint, equality constraints from that joint to both physical fingers, and separate position actuators to both fingers. Contact could therefore make the equality solver and three servo targets fight over the same physical aperture.

V8 keeps the public 14-value D0/native boundary but removes the overdetermined internal plant:

- the scalar aperture maps directly to `+0.5/-0.5` targets for the two physical finger joints;
- the compatibility aperture joint is neither actuated nor used as measured feedback;
- there are no gripper equality constraints;
- measured aperture is the physical finger separation;
- each physical finger uses bounded `kp=2500`, `kv=60`, `8 N` force, `0.1 kg` armature, and `2 N s/m` damping;
- flat-pad sliding friction is `1.5`;
- status output reports finger targets, tracking error, symmetry error, and forces.

The left/right code paths are structurally symmetric. Because this run included no raw log, v8 also adds per-joint target, measured position, error, saturation, actuator force, and IK-failure diagnostics for each arm. A new physical run is required before changing either arm's mapping or gain independently.

## Required evidence

1. Run the full M1 NVIDIA EGL verifier and retain freshly generated result/parity artifacts.
2. Run the v8 Quest profile and retain stdout.
3. Confirm that released triggers hold at least `95 mm` aperture during multi-joint motion.
4. Confirm stable bilateral cube grasp during wrist motion.
5. Compare `arm_plant.left` and `arm_plant.right` in the status records if the right arm still lags.
