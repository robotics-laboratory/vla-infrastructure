# MuJoCo Quest physical run 10 — failed

Date: 2026-09-28

Status: failed physical observation; not acceptance evidence.

Input log attachment SHA-256:
`58a9618d2c29a42068dbc3989eaae271349d012e618da6bcdcce8a33b404efe1`

The operator reported that both arms felt obstructed and could not reliably
reach the cubes. The run does not support a joint-map regression: recorded IK
failures and Cartesian saturation were both zero, and the v20 increment had not
changed the arm IK, gains, limits, or OpenXR basis.

The gripper/contact diagnostics contradicted the v20 force workaround. At an
open target of 100 mm the physical aperture reached 111.750 mm on one side;
maximum physical-finger symmetry error reached 7.206 mm left and 8.454 mm
right. Final saturation totals included 142 gripper and 161 gripper-force
events. These values are consistent with unintended external contacts acting
on the oversized finger collision boxes.

Disposition:

- remove the v19/v20 directional 12 N opening-force experiment;
- restore symmetric `[-8, +8] N` physical-finger actuator limits;
- preserve the previously accepted arm sensitivity, IK persistence, joint
  limits, and OpenXR mapping;
- replace each `56 x 76 x 12 mm` full-bounding-box finger collision with a
  thin distal `48 x 42 x 2 mm` grasp pad;
- reopen automated NVIDIA EGL and physical Quest validation for M1 v17 / Quest
  v21.
