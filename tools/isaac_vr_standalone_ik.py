"""CPU-only pinned Piper ovphysx mapping; no simulation and no custom IK solver.

Source: isaaclab_ov/assets/articulation/kernels.py:192 COM->link shift.
Caller supplies ONE completed immutable snapshot; run upstream controller on CPU.
"""

from __future__ import annotations
import numpy as np

DOFS = tuple([f"joint{i}" for i in range(1, 7)] + ["gripper", "gripper_joint1", "gripper_joint2"])
BODIES = (
    "base_link",
    "link1",
    "link2",
    "link3",
    "link4",
    "link5",
    "link6",
    "flange_link",
    "gripper_base",
    "gripper_link",
    "gripper_link1",
    "gripper_link2",
)


def piper_ik_state(
    *, q, link_poses_xyzw, com_poses_xyzw, jacobian_com, limits, body_names, dof_names, fixed_base
):
    """Return arrays for two arms. Strict pinned topology; all inputs native order.

    q[2,9], poses/COM[2,12,7], raw J[2,66,9], limits[2,9,2].
    gripper_base is current run_isaac_s1.py:483 TCP, backend index8/Jbody7.
    DOF/body exact order is from the successful fixedbase-v3 receipt. Reject
    changed ordering/signs until re-audited; metadata names cannot prove signs.
    """
    if not fixed_base or tuple(body_names) != BODIES or tuple(dof_names) != DOFS:
        raise ValueError("unreviewed Piper articulation topology/order")
    expected = [
        (q, (2, 9)),
        (link_poses_xyzw, (2, 12, 7)),
        (com_poses_xyzw, (2, 12, 7)),
        (jacobian_com, (2, 66, 9)),
        (limits, (2, 9, 2)),
    ]
    arrays = []
    for value, shape in expected:
        a = np.asarray(value, dtype=np.float32)
        if a.shape != shape or not np.isfinite(a).all():
            raise ValueError(f"invalid state shape/data; expected {shape}")
        arrays.append(a)
    q, poses, com, jac, limits = arrays
    body, row = BODIES.index("gripper_base"), BODIES.index("gripper_base") - 1
    xyzw = poses[:, body, 3:]
    if not np.allclose(np.linalg.norm(xyzw, axis=1), 1, atol=1e-4, rtol=0):
        raise ValueError("nonunit link quaternion")
    v = com[:, body, :3]
    t = 2 * np.cross(xyzw[:, :3], v)
    r = v + xyzw[:, 3:] * t + np.cross(xyzw[:, :3], t)
    j = jac.reshape(2, 11, 6, 9)[:, row, :, :6].copy()
    j[:, :3, :] -= np.cross(j[:, 3:, :].transpose(0, 2, 1), r[:, None, :]).transpose(0, 2, 1)
    result = dict(
        q=q[:, :6].copy(),
        jacobian=j,
        limits=limits[:, :6].copy(),
        tcp_pose_w=poses[:, body, [0, 1, 2, 6, 3, 4, 5]].copy(),
        root_pose_w=poses[:, 0, [0, 1, 2, 6, 3, 4, 5]].copy(),
    )
    for a in result.values():
        a.setflags(write=False)
    return result
