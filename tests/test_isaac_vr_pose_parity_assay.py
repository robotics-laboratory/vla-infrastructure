from __future__ import annotations

import numpy as np
import pytest
from types import SimpleNamespace

from tools.isaac_vr_pose_parity_assay import (
    PoseIdentity,
    PoseParityError,
    PoseThresholds,
    _capture_native,
    _native_articulation,
    _project_fabric_frame,
    compare_pose_frame,
    qualify_pose_sequence,
    quaternion_error_rad,
    xyzw_to_wxyz,
)


IDENTITIES = (
    PoseIdentity(
        "robot",
        ("/World/Robot", "/World/Robot/link"),
        "articulation",
        motion="any",
        motion_paths=("/World/Robot/link",),
    ),
    PoseIdentity("object", ("/World/Object",), "rigid_body"),
    PoseIdentity("camera", ("/World/Camera",), "camera"),
)


def _frames(delta: float = 0.0):
    frame = {
        "robot": {
            "positions": np.array([[0, 0, 0], [1 + delta, 0, 0]], dtype=np.float32),
            "orientations": np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.float32),
        },
        "object": {
            "position": np.array([delta, 1, 0], dtype=np.float32),
            "orientation": np.array([1, 0, 0, 0], dtype=np.float32),
        },
        "camera": {
            "position": np.array([0, delta, 2], dtype=np.float32),
            "orientation": np.array([1, 0, 0, 0], dtype=np.float32),
        },
    }
    return frame


def test_xyzw_conversion_and_quaternion_sign_are_explicit():
    np.testing.assert_array_equal(xyzw_to_wxyz([1, 2, 3, 4]), [4, 1, 2, 3])
    np.testing.assert_allclose(
        quaternion_error_rad([[1, 0, 0, 0]], [[-1, 0, 0, 0]]),
        [0.0],
    )


def test_compare_pose_frame_accepts_complete_bounded_parity():
    native = _frames()
    fabric = _frames()
    fabric["camera"]["position"][0] += 0.5e-5
    result = compare_pose_frame(fabric, native, IDENTITIES)
    assert result["passed"] is True
    assert len(result["entities"]) == 4
    assert result["maximum_position_error_m"] == pytest.approx(0.5e-5)


@pytest.mark.parametrize(
    "mutation", ("missing_group", "missing_channel", "bad_shape", "nan", "zero_quaternion")
)
def test_compare_pose_frame_fails_closed_on_incomplete_or_invalid_inputs(mutation):
    fabric = _frames()
    native = _frames()
    if mutation == "missing_group":
        del fabric["camera"]
    elif mutation == "missing_channel":
        del native["object"]["orientation"]
    elif mutation == "bad_shape":
        fabric["robot"]["positions"] = np.zeros((1, 3))
    elif mutation == "nan":
        native["camera"]["position"][0] = np.nan
    else:
        fabric["object"]["orientation"][:] = 0
    with pytest.raises(PoseParityError):
        compare_pose_frame(fabric, native, IDENTITIES)


def test_threshold_breach_is_reported_not_hidden():
    fabric = _frames()
    native = _frames()
    fabric["object"]["position"][0] += 2.0e-5
    result = compare_pose_frame(fabric, native, IDENTITIES)
    assert result["passed"] is False
    failed = [row for row in result["entities"] if not row["passed"]]
    assert [(row["kind"], row["path"]) for row in failed] == [("rigid_body", "/World/Object")]


def test_sequence_requires_declared_robot_object_and_camera_motion():
    first = _frames(0.0)
    second = _frames(0.001)
    report = qualify_pose_sequence((first, second), (first, second), IDENTITIES)
    assert report["passed"] is True
    assert all(item["passed"] for item in report["motion"])


def test_sequence_rejects_static_required_camera():
    first = _frames(0.0)
    second = _frames(0.001)
    second["camera"] = {name: value.copy() for name, value in first["camera"].items()}
    report = qualify_pose_sequence((first, second), (first, second), IDENTITIES)
    assert report["passed"] is False
    camera = next(item for item in report["motion"] if item["group"] == "camera")
    assert camera["passed"] is False


def test_custom_thresholds_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        PoseThresholds(position_m=0.0)


def test_articulation_mapping_uses_physical_root_and_excludes_container_xform():
    robot = SimpleNamespace(
        body_names=("base_link", "link1"),
        data=SimpleNamespace(
            root_pose_w=np.array([[1, 2, 3, 0, 0, 0, 1]], dtype=np.float32),
            body_link_pose_w=np.array(
                [[[1, 2, 3, 0, 0, 0, 1], [4, 5, 6, 0, 0, 1, 0]]],
                dtype=np.float32,
            ),
        ),
    )
    recordable = SimpleNamespace(
        group="robot",
        prim_path="/World/Robot",
        link_paths=("/World/Robot", "/World/Robot/base_link", "/World/Robot/base_link/link1"),
    )
    identity, native = _native_articulation(robot, recordable)
    assert identity.paths == ("/World/Robot/base_link", "/World/Robot/base_link/link1")
    assert identity.motion_paths == ("/World/Robot/base_link/link1",)
    np.testing.assert_array_equal(native["positions"], [[1, 2, 3], [4, 5, 6]])

    raw = {
        "robot": {
            "positions": np.array([[99, 99, 99], [1, 2, 3], [4, 5, 6]]),
            "orientations": np.tile([1, 0, 0, 0], (3, 1)),
        }
    }
    projected = _project_fabric_frame(raw, (recordable,), (identity,))
    np.testing.assert_array_equal(projected["robot"]["positions"], [[1, 2, 3], [4, 5, 6]])


def test_camera_native_source_uses_opengl_tensor_matching_usd_camera_axes():
    recordable = SimpleNamespace(group="camera", prim_path="/World/Camera")
    source = SimpleNamespace(
        data=SimpleNamespace(
            pos_w=np.array([[1, 2, 3]], dtype=np.float32),
            quat_w_world=np.array([[0, 0, 0, 1]], dtype=np.float32),
            quat_w_opengl=np.array([[1, 0, 0, 0]], dtype=np.float32),
        )
    )
    _, frame = _capture_native((recordable,), {"camera": ("camera", source)})
    np.testing.assert_array_equal(frame["camera"]["orientation"], [0, 1, 0, 0])
