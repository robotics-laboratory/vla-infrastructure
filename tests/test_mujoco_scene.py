"""Contract checks for the concrete dual-cube MuJoCo scene."""

from __future__ import annotations

from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml"


def test_task_scene_contains_only_the_frozen_task_entities_and_views() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    assert (model.nq, model.nv, model.nu, model.neq) == (32, 30, 14, 2)
    np.testing.assert_allclose(model.opt.timestep, 1.0 / 240.0, atol=0.0, rtol=0.0)
    assert {model.camera(index).name for index in range(model.ncam)} == {
        "left_wrist",
        "right_wrist",
        "scene",
    }
    assert [model.light(index).name for index in range(model.nlight)] == [
        "cool_fill",
        "warm_key",
    ]
    for side in ("left", "right"):
        assert model.body(f"{side}_cube").id >= 0
        assert model.geom(f"{side}_plate").id >= 0


def test_wrist_cameras_look_along_each_gripper_approach_axis() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)

    for side in ("left", "right"):
        camera_rotation = data.cam_xmat[model.camera(f"{side}_wrist").id].reshape(3, 3)
        gripper_rotation = data.body(f"{side}_gripper_base").xmat.reshape(3, 3)
        camera_forward = -camera_rotation[:, 2]
        gripper_forward = gripper_rotation[:, 2]
        np.testing.assert_allclose(camera_forward, gripper_forward, atol=1.0e-6)


def test_gripper_uses_explicit_pad_contacts_and_compliant_aperture_tendons() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    assert model.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC
    assert model.opt.impratio == 10.0
    assert model.opt.noslip_iterations == 0

    for side in ("left", "right"):
        for index in (1, 2):
            pad = model.geom(f"{side}_gripper_pad{index}")
            np.testing.assert_allclose(pad.pos, [0.0, -0.043, 0.001])
            np.testing.assert_allclose(pad.size, [0.028, 0.033, 0.001])
            assert int(pad.condim.item()) == 6
            np.testing.assert_allclose(pad.friction, [1.5, 0.005, 0.0001])
            assert int(pad.contype.item()) == 0
            assert int(pad.conaffinity.item()) == 0
            finger_id = model.body(f"{side}_gripper_link{index}").id
            collidable = [
                geom_id
                for geom_id in range(model.ngeom)
                if int(model.geom_bodyid[geom_id]) == finger_id
                and int(model.geom_contype[geom_id]) != 0
            ]
            assert collidable == []

            joint = model.joint(f"{side}_gripper_joint{index}")
            assert joint.stiffness == 0.0
        actuator = model.actuator(f"{side}_gripper_aperture_position")
        assert actuator.gainprm[0] == 1250.0
        assert actuator.biasprm[1] == -1250.0
        assert actuator.biasprm[2] == -30.0
        np.testing.assert_allclose(actuator.forcerange, [-8.0, 8.0])
        tendon = model.tendon(f"{side}_gripper_aperture")
        np.testing.assert_allclose(model.tendon_range[tendon.id], [0.0, 0.1])
        center = model.tendon(f"{side}_gripper_center")
        assert model.tendon_stiffness[center.id] == 0.0
        constraint = model.equality(f"{side}_gripper_center_constraint")
        np.testing.assert_allclose(model.eq_solref[constraint.id], [0.02, 1.0])
        np.testing.assert_allclose(
            model.eq_solimp[constraint.id, :3], [0.9, 0.95, 0.001]
        )
        for index in (1, 2):
            pair = model.pair(f"{side}_pad{index}_cube_contact")
            assert int(pair.dim.item()) == 6
            np.testing.assert_allclose(
                pair.friction, [1.5, 1.5, 0.005, 0.0001, 0.0001]
            )
            np.testing.assert_allclose(pair.solref, [0.02, 1.0])
            np.testing.assert_allclose(pair.solimp[:3], [0.9, 0.95, 0.001])
    assert model.neq == 2


def test_rendering_separates_visual_and_collision_geometry() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))

    for name in (
        "floor",
        "table",
        "backdrop",
        "left_plate",
        "right_plate",
        "left_cube_geom",
        "right_cube_geom",
    ):
        assert int(model.geom(name).group.item()) == 1

    for side in ("left", "right"):
        body = model.body(f"{side}_link6")
        groups = {
            int(model.geom_group[geom_id])
            for geom_id in range(model.ngeom)
            if int(model.geom_bodyid[geom_id]) == body.id
        }
        assert groups == {0, 1}


def test_task_scene_home_settles_without_robot_or_object_instability() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    initial_robot = data.qpos[:18].copy()
    for side in ("left", "right"):
        for index in range(1, 7):
            data.actuator(f"{side}_joint{index}_position").ctrl = data.joint(
                f"{side}_joint{index}"
            ).qpos
        data.actuator(f"{side}_gripper_aperture_position").ctrl = (
            data.joint(f"{side}_gripper_joint1").qpos[0]
            - data.joint(f"{side}_gripper_joint2").qpos[0]
        )
    for _ in range(240):
        mujoco.mj_step(model, data)
    assert np.isfinite(data.qpos).all()
    assert np.max(np.abs(data.qpos[:18] - initial_robot)) < 1e-3
    for side in ("left", "right"):
        np.testing.assert_allclose(data.body(f"{side}_cube").xpos[2], 0.844943, atol=1e-5)
        assert np.linalg.norm(data.body(f"{side}_cube").cvel[3:]) < 1e-6
