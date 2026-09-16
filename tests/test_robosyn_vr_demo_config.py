"""Isolation checks for physical-demo tuning candidates."""

from pathlib import Path
import math

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _rotate_vector_xyzw(
    quaternion: list[float], vector: tuple[float, float, float]
) -> tuple[float, float, float]:
    x, y, z, w = quaternion
    vx, vy, vz = vector
    # Expanded q * v * q^-1 rotation; keeps this config test dependency-free.
    return (
        (1.0 - 2.0 * (y * y + z * z)) * vx
        + 2.0 * (x * y - z * w) * vy
        + 2.0 * (x * z + y * w) * vz,
        2.0 * (x * y + z * w) * vx
        + (1.0 - 2.0 * (x * x + z * z)) * vy
        + 2.0 * (y * z - x * w) * vz,
        2.0 * (x * z - y * w) * vx
        + 2.0 * (y * z + x * w) * vy
        + (1.0 - 2.0 * (x * x + y * y)) * vz,
    )


def test_physical_retest_values_are_demo_only_and_geometry_is_unchanged() -> None:
    config = yaml.safe_load(
        (ROOT / "configs/experiments/robosyn_vr_demo.yaml").read_text(encoding="utf-8")
    )
    assert config["status"] == "EXPERIMENTAL_TEST_ONLY_NOT_A_GATE"
    gripper = config["demo_physics"]["gripper_contact"]
    assert gripper["canonical_geometry_change"] == "none"
    assert gripper["leader_joint"] == "gripper"
    assert gripper["leader_drive"] == {
        "effort_limit_n": 2.0,
        "velocity_limit_m_s": 3.0,
        "stiffness_n_m": 400.0,
        "damping_n_s_m": 40.0,
    }
    assert gripper["mimic_follower_joint_expr"] == "gripper_joint[1-2]"
    assert gripper["mimic_follower_drive"]["stiffness_n_m"] == 0.0
    assert gripper["mimic_follower_drive"]["damping_n_s_m"] == 0.0
    assert config["scene"]["robot_bases_m"] == {
        "left": [0.233, 0.3, 0.825],
        "right": [0.233, -0.3, 0.825],
    }
    assert config["scene"]["table"]["center_m"] == [0.725, 0.0, 0.775]
    assert config["scene"]["table"]["size_m"] == [1.0, 1.0, 0.1]

    presentation = config["xr_presentation"]
    assert presentation["anchor_pos_m"] == [-0.05, 0.0, -0.1]
    assert presentation["scale"] == 1.0
    assert presentation["recenter"] == {
        "toggle_control": "right_thumbstick_click",
        "quest_button": "R3",
        "view_prim_path": "/World/RobosynDemo/SceneCamera",
        "behavior": (
            "One rising edge uses XRCore.schedule_teleport_to_view so the current physical "
            "HMD pose matches the validated demo scene-camera pose; controller poses use "
            "XRCore's full physical-to-virtual transform including the resulting space "
            "origin, while robot/table USD geometry and 1:1 scale remain unchanged."
        ),
    }

    sensitivity = config["teleop_tuning"]["sensitivity"]
    assert sensitivity["control_mode"] == "slider"
    assert sensitivity["input_control"] == "thumbstick_x"
    assert sensitivity["input_range"] == [-1.0, 1.0]
    assert sensitivity["scope"] == "independent per arm"
    assert sensitivity["slider"] == {
        "minimum": {"translation_scale": 2.0, "rotation_scale": 2.0},
        "center": {"translation_scale": 4.0, "rotation_scale": 4.0},
        "maximum": {"translation_scale": 6.0, "rotation_scale": 6.0},
    }
    assert config["vr_camera_feeds"]["toggle_control"] == "left_primary_click"
    assert config["vr_camera_feeds"]["quest_button"] == "X"
    assert config["vr_camera_feeds"]["upload_path"] == "cpu_staged"
    assert config["vr_camera_feeds"]["layout"]["placement"] == "head_locked"
    assert config["vr_camera_feeds"]["layout"]["center_offset_m"] == [0.0, -0.18]
    assert config["vr_camera_feeds"]["layout"]["distance_m"] == 0.65
    assert config["vr_camera_feeds"]["layout"]["panel_width_m"] == 0.36

    backdrop = config["scene"]["backdrop"]
    assert backdrop["toggle_control"] == "right_secondary_click"
    assert backdrop["quest_button"] == "B"
    assert backdrop["initial_visibility"] is True


def test_wrist_camera_looks_along_gripper_approach_and_is_upright() -> None:
    config = yaml.safe_load(
        (ROOT / "configs/experiments/robosyn_vr_demo.yaml").read_text(encoding="utf-8")
    )
    camera = config["cameras"]["wrist"]

    assert camera["offset_xyz_m"] == [0.06, 0.0, 0.0]
    assert math.isclose(sum(value * value for value in camera["offset_quat_xyzw"]), 1.0)
    assert _rotate_vector_xyzw(camera["offset_quat_xyzw"], (1.0, 0.0, 0.0)) == (
        0.0,
        0.0,
        1.0,
    )
    assert _rotate_vector_xyzw(camera["offset_quat_xyzw"], (0.0, 0.0, 1.0)) == (
        1.0,
        0.0,
        0.0,
    )
    assert camera["optical_axis_parent"] == "+Z"
    assert camera["up_axis_parent"] == "+X"
