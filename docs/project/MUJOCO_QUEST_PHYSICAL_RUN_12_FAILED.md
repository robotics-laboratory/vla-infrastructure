# MuJoCo Quest physical run 12 — failed

Date: 2026-09-29

Profile: `piperx_mujoco_quest_teleop_v24`

Status: `FAILED`; this run reopens the automated v24 assumptions and is not M1
acceptance evidence.

## Retained source

- Operator-provided stdout SHA-256:
  `2003342b9be06e61de947d558dce355a85a60400f06295b10c423456383aa05a`
- Bounded run: 1,629 control steps, 2 explicit resets, 1,404 valid tracking
  frames per arm, zero loop overruns, zero reported IK exceptions, and no
  teardown failure.
- Final saturation totals: 363 any, 103 gripper slew, 320 gripper force, zero
  Cartesian, and zero joint saturation frames.

## Human observations

- A manually acquired cube still escaped and the closed gripper chattered.
- When both controllers were deliberately moved down, the left arm moved partly
  down while the right arm moved mainly sideways.

## Diagnostic conclusion

The absence of IK exceptions and joint/Cartesian clipping does not establish
correct Cartesian response. V24 used equal position and orientation weights;
logged incidental wrist rotations were much larger numerically than millimetre
translations and produced different joint motion from the mirrored homes.

The prolonged force limiting also contradicts the retained test's idealised
teleported, centred grasp. The two finger position servos plus hard symmetry
equality over-constrained contact and could not accommodate an off-centre cube.

## Required revalidation

Candidate v25/M1 v21 must demonstrate all of the following before another
physical acceptance attempt:

1. The real Placo edge sends identical down intent downward on both mirrored
   arms with bounded lateral leakage.
2. A cube beginning on the canonical table is approached, contacted by both
   pads, and lifted; teleport-only retention is insufficient.
3. The compliant aperture-tendon plant retains laterally and longitudinally
   offset cubes during wrist motion.
4. The complete five-file suite and NVIDIA EGL M1 verifier pass with newly
   retained hashes.

