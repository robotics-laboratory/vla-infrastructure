# MuJoCo Quest physical run 11 — partial

Date: 2026-09-28

Status: partial physical observation; not acceptance evidence.

Input log attachment SHA-256:
`52e0ede4616987a288ef74ecdec050382f4c6a4a26bbdf25ef2712e23290fd38`

The operator reported that cube pickup improved but the cube still fell during
motion. Arm control itself recovered: the run finished with zero IK failures,
zero Cartesian saturation, and zero loop overruns.

The log distinguishes grasp from command failure. With a closed `0 mm` target,
the right and left physical apertures repeatedly stopped around `35-38 mm` at
the symmetric `[-8,+8] N` force limits, consistent with bilateral contact on a
40 mm cube. Later the aperture approached zero, showing that the cube had left
the contact rather than the gripper failing to close. Across the run the final
force-saturation count was 859 frames.

STL audit found that the nominal cube centre maps near finger-local `y=-38 mm`.
The v17 distal pad ends at `y=-34 mm`, so only about 24 mm of the cube's 40 mm
longitudinal face overlaps it. The actual mesh continues through a narrow
sloped inner surface to `y=-10 mm`. M1 v18 therefore keeps the successful thin
distal pad and adds a thin proximal ramp matching that STL surface. Force,
friction, equality, IK, sensitivity, and the external action remain unchanged.
