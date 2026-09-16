"""Offline regression tests for the concrete S1/D0 Isaac edge."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from tools.isaac_s1_runtime import (
    ISAAC_ARM_JOINT_NAMES,
    d0_action_to_native,
    materialize_gate_c_urdf,
    native_observation_to_d0,
    transform_error,
)


ROOT = Path(__file__).resolve().parents[1]


def test_d0_action_mapping_preserves_label_order_units_and_identity() -> None:
    label = np.asarray(
        [10.0, 30.0, -60.0, 15.0, 20.0, -25.0, -5.0, -10.0, 45.0, -70.0, -15.0, 25.0, 35.0, 125.0]
    )
    original = label.copy()
    native = d0_action_to_native(label)
    np.testing.assert_array_equal(label, original)
    np.testing.assert_allclose(native.left_rad_m[:6], np.deg2rad(label[:6]))
    np.testing.assert_allclose(native.right_rad_m[:6], np.deg2rad(label[7:13]))
    assert native.left_rad_m[6] == 0.0
    assert native.right_rad_m[6] == 0.1
    assert native.saturated
    assert ISAAC_ARM_JOINT_NAMES == (
        "joint1",
        "joint2",
        "joint3",
        "joint4",
        "joint5",
        "joint6",
        "gripper",
    )


def test_native_observation_mapping_is_left_then_right_and_keeps_uint8_rgb() -> None:
    left = np.concatenate((np.deg2rad([1, 2, -3, 4, 5, 6]), [-0.025]))
    right = np.concatenate((np.deg2rad([-1, 20, -30, -4, 5, -6]), [0.075]))
    left_rgba = np.zeros((480, 640, 4), dtype=np.uint8)
    left_rgba[..., 0] = 17
    right_rgb = np.full((480, 640, 3), 23, dtype=np.uint8)
    observation = native_observation_to_d0(left, right, left_rgba, right_rgb)
    np.testing.assert_allclose(
        observation["observation.state"],
        [1, 2, -3, 4, 5, 6, 25, -1, 20, -30, -4, 5, -6, 75],
        atol=1e-12,
    )
    assert observation["observation.state"].shape == (14,)
    assert observation["observation.state"].dtype == np.float32
    assert observation["observation.images.left_wrist"].shape == (480, 640, 3)
    assert observation["observation.images.left_wrist"].dtype == np.uint8
    assert observation["observation.images.left_wrist"][0, 0].tolist() == [17, 0, 0]
    assert observation["observation.images.right_wrist"][0, 0].tolist() == [23, 23, 23]


def test_s1_config_keeps_process_boundary_and_30_hz_decimation() -> None:
    config = yaml.safe_load((ROOT / "configs/isaac_s1_runtime.yaml").read_text(encoding="utf-8"))
    assert config["environment"]["lerobot_allowed"] is False
    assert config["environment"]["isaac_lab_commit"] == ("913ac53f51b2f8d02c9e121caa4cbdd06262948e")
    assert config["environment"]["upstream_frozen_workspace"] is True
    assert config["environment"]["upstream_override_conflicts"] == 11
    assert config["environment"]["materialized_path"] == (
        "/data/vla-infrastructure/envs/isaac-s1-candidate-b"
    )
    assert config["execution"]["action_repeat"] == 4
    assert config["execution"]["physics_dt_s"] * 4 == config["execution"]["control_dt_s"]
    assert config["cameras"]["fps"] == 30
    assert config["cameras"]["sensor_layout"].startswith("One upstream Isaac Lab Camera")
    assert "/gripper_base/S1WristCamera" in config["cameras"]["left_wrist"]["prim_path"]
    assert "/gripper_base/S1WristCamera" in config["cameras"]["right_wrist"]["prim_path"]
    assert config["cameras"]["pose_update"].startswith("Upstream parent hierarchy")
    assert config["d0_boundary"]["state_shape"] == [14]
    contract = yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text(encoding="utf-8"))
    assert config["d0_boundary"]["order_source"] == (
        "configs/resolved_contract.yaml#dataset.observation_contract.state.names"
    )
    assert len(contract["dataset"]["observation_contract"]["state"]["names"]) == 14


def test_s1_runtime_uses_only_upstream_camera_path() -> None:
    source = (ROOT / "tools/run_isaac_s1.py").read_text(encoding="utf-8")
    assert ".set_world_poses(" not in source
    assert "omni.replicator" not in source
    assert "reload_render_preset" not in source
    assert "use_fabric=False" not in source
    assert "CameraCfg(" in source
    assert "regex-batched FrameView over parented wrist prims" in source


@pytest.mark.parametrize(
    ("launcher", "profile"),
    (
        ("launch_isaac_s1.py", "isaac-s1"),
        ("launch_isaac_s2.py", "isaac-s2"),
        ("launch_isaac_robosyn_vr_demo.py", "robosyn-vr-demo"),
    ),
)
def test_isaac_launchers_use_explicit_kit_portable_roots(
    launcher: str, profile: str
) -> None:
    source = (ROOT / "tools" / launcher).read_text(encoding="utf-8")
    assert f'RUNTIME_ROOT = STORAGE / "cache/{profile}"' in source
    assert 'USER_CACHE_ROOT = RUNTIME_ROOT / "users" / f"uid-{os.getuid()}"' in source
    assert 'KIT_PORTABLE_ROOT = USER_CACHE_ROOT / "kit"' in source
    assert '"XDG_CACHE_HOME": str(USER_CACHE_ROOT / "xdg")' in source
    assert 'f"--portable-root {KIT_PORTABLE_ROOT}"' in source


def test_materialized_urdf_keeps_gate_c_frames_and_meshes(tmp_path: Path) -> None:
    # Exact source is already checked into Gate C; reconstruct its upstream CRLF bytes.
    source = tmp_path / "source"
    asset_dir = source / "piper_x/urdf"
    asset_dir.mkdir(parents=True)
    checked_in = ROOT / "artifacts/piper_x/f6642ce0d7872c686f29c99e9e10cd23d1d49313"
    for name in ("piper_x_description.urdf", "piper_x_with_gripper_description.xacro"):
        (asset_dir / name).write_bytes((checked_in / name).read_bytes().replace(b"\n", b"\r\n"))
    output = tmp_path / "piper_x_gate_c.urdf"
    digest = materialize_gate_c_urdf(source, output)
    text = output.read_text(encoding="utf-8")
    assert len(digest) == 64
    assert '<link name="flange_link">' in text
    assert '<link name="gripper_base">' in text
    assert '<joint name="gripper" type="prismatic">' in text
    assert '<mass value="0.001"' in text
    assert "package://agx_arm_description" in text
    assert "xacro:include" not in text


def test_transform_error_is_zero_for_identical_transforms() -> None:
    transform = np.eye(4)
    assert transform_error(transform, transform) == (0.0, 0.0)


@pytest.mark.parametrize("action", [[0.0] * 13, [float("nan")] * 14, [float("inf")] * 14])
def test_invalid_action_is_rejected_before_actuation(action) -> None:
    with pytest.raises(ValueError):
        d0_action_to_native(action)
