"""Milestone-1 MuJoCo model and Gate C parity checks."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import mujoco
import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "f6642ce0d7872c686f29c99e9e10cd23d1d49313"
ARM_DIR = ROOT / "assets/mujoco/piper_x" / COMMIT
ARM_PATH = ARM_DIR / "piper_x.xml"
SCENE_PATH = ROOT / "assets/mujoco/scenes/piper_x_bimanual_empty_v1.xml"
TASK_SCENE_PATH = ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml"
CONFIG_PATH = ROOT / "configs/mujoco_m1_runtime.yaml"
MODEL_CONTRACT_PATH = ROOT / "configs/piper_x_model_contract.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tcp_transform(model: mujoco.MjModel, q_deg: list[float], prefix: str = "") -> np.ndarray:
    data = mujoco.MjData(model)
    for index, value in enumerate(q_deg, start=1):
        data.joint(f"{prefix}joint{index}").qpos = math.radians(value)
    mujoco.mj_forward(model, data)
    body = data.body(f"{prefix}gripper_base")
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = body.xmat.reshape(3, 3)
    transform[:3, 3] = body.xpos
    return transform


def test_frozen_m1_task_contract_matches_the_accepted_gate() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["status"] == "GATE_M1_REVALIDATION_REQUIRED"
    assert config["model"]["source_commit"] == COMMIT
    assert config["task"]["task_id"] == "PiperX-DualCubeToMatchingPlate-v1"
    assert config["task"]["revision"] == "dual_cube_plate_success_v1"
    assert config["task"]["horizon_control_ticks"] == 300
    assert config["task"]["success"]["per_side"] == {
        "cube_center_xy_distance_to_plate_center_max_m": 0.06,
        "robot_cube_contacts_required": 0,
        "cube_linear_speed_strictly_below_m_s": 0.05,
        "consecutive_control_ticks": 5,
    }
    np.testing.assert_allclose(
        config["execution"]["physics_dt_s"] * config["execution"]["action_repeat"],
        config["execution"]["control_dt_s"],
        rtol=0.0,
        atol=1.0e-15,
    )
    assert config["execution"]["integrator"] == "implicitfast"
    assert config["gate_status"]["M1"] == "revalidation_required"


def test_manifest_closes_source_and_generated_asset_hashes() -> None:
    manifest = json.loads((ARM_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["commit"] == COMMIT
    assert manifest["builder"]["sha256"] == _sha256(ROOT / manifest["builder"]["path"])
    assert manifest["runtime"]["mujoco_version"] == "3.9.0"
    assert manifest["conversion"]["mesh_strategy"] == "collision_stl_as_initial_visual_v1"
    assert manifest["outputs"]["canonical_mjcf"]["sha256"] == _sha256(ARM_PATH)
    assert manifest["outputs"]["empty_bimanual_mjcf"]["sha256"] == _sha256(SCENE_PATH)
    assert manifest["outputs"]["task_scene_mjcf"]["sha256"] == _sha256(TASK_SCENE_PATH)
    for mesh in manifest["outputs"]["meshes"]:
        assert _sha256(ARM_DIR / mesh["path"]) == mesh["sha256"]


def test_single_arm_has_gate_c_names_limits_and_aperture_tendon_actuation() -> None:
    model = mujoco.MjModel.from_xml_path(str(ARM_PATH))
    expected_joints = [
        "joint1",
        "joint2",
        "joint3",
        "joint4",
        "joint5",
        "joint6",
        "gripper",
        "gripper_joint1",
        "gripper_joint2",
    ]
    assert [model.joint(index).name for index in range(model.njnt)] == expected_joints
    assert (model.nq, model.nv, model.nu, model.neq) == (9, 9, 7, 1)

    contract = yaml.safe_load(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
    for mapping in contract["joint_mapping"]:
        expected = np.deg2rad(mapping["limits_deg"])
        np.testing.assert_allclose(model.joint(mapping["urdf_name"]).range, expected, atol=2e-5)
    np.testing.assert_allclose(model.joint("gripper").range, [0.0, 0.1], atol=2e-5)

    assert [model.actuator(index).name for index in range(model.nu)] == [
        *[f"joint{index}_position" for index in range(1, 7)],
        "gripper_aperture_position",
    ]
    aperture = model.actuator("gripper_aperture_position")
    assert aperture.gainprm[0] == 1250.0
    assert aperture.biasprm[1] == -1250.0
    assert aperture.biasprm[2] == -30.0
    np.testing.assert_allclose(aperture.forcerange, [-8.0, 8.0])
    tendon = model.tendon("gripper_aperture")
    np.testing.assert_allclose(model.tendon_range[tendon.id], [0.0, 0.1])
    center = model.tendon("gripper_center")
    assert model.tendon_stiffness[center.id] == 0.0
    constraint = model.equality("gripper_center_constraint")
    np.testing.assert_allclose(model.eq_solref[constraint.id], [0.02, 1.0])
    np.testing.assert_allclose(model.eq_solimp[constraint.id, :3], [0.9, 0.95, 0.001])
    for follower in ("gripper_joint1", "gripper_joint2"):
        joint = model.joint(follower)
        assert joint.stiffness == 0.0


def test_mujoco_fk_and_positive_directions_match_gate_c_references() -> None:
    model = mujoco.MjModel.from_xml_path(str(ARM_PATH))
    contract = yaml.safe_load(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
    verification = contract["verification"]
    for reference in verification["fk_references"].values():
        actual = _tcp_transform(model, reference["q_deg"])
        expected = np.asarray(reference["T_base_tcp"], dtype=np.float64)
        np.testing.assert_allclose(actual, expected, atol=5e-4, rtol=0.0)

    direction = verification["positive_direction_reference"]
    for index, mapping in enumerate(contract["joint_mapping"]):
        q_deg = list(direction["q_deg"])
        q_deg[index] += direction["delta_deg"]
        actual = _tcp_transform(model, q_deg)
        expected = np.asarray(direction["T_base_tcp"][mapping["plugin_name"]], dtype=np.float64)
        np.testing.assert_allclose(actual, expected, atol=5e-4, rtol=0.0)


def test_bimanual_scene_namespaces_instances_and_reproduces_home_tcp() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    assert (model.nq, model.nv, model.nu, model.neq) == (18, 18, 14, 2)
    for side in ("left", "right"):
        for name in (*[f"joint{index}" for index in range(1, 7)], "gripper"):
            assert model.joint(f"{side}_{name}").id >= 0
        assert model.body(f"{side}_base_link").id >= 0
        assert model.body(f"{side}_gripper_base").id >= 0
        assert model.site(f"{side}_tcp").id >= 0

    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)
    np.testing.assert_allclose(data.body("left_base_link").xpos, [0.233, 0.300, 0.825], atol=1e-12)
    np.testing.assert_allclose(
        data.body("right_base_link").xpos, [0.233, -0.300, 0.825], atol=1e-12
    )
    np.testing.assert_allclose(
        np.linalg.norm(data.body("left_base_link").xpos - data.body("right_base_link").xpos),
        0.6,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        data.body("left_gripper_base").xpos, [0.578929, 0.174092, 1.026481], atol=5e-4
    )
    np.testing.assert_allclose(
        data.body("right_gripper_base").xpos, [0.578929, -0.174092, 1.026481], atol=5e-4
    )


def test_bimanual_home_has_no_adjacent_link_contacts_and_remains_bounded() -> None:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    assert model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    assert model.nexclude == 22
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)
    assert data.ncon == 0
    initial_qpos = data.qpos.copy()
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
    assert np.max(np.abs(data.qpos - initial_qpos)) < 1e-3
