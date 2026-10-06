from __future__ import annotations

import sys
import numpy as np
import pytest
from types import ModuleType, SimpleNamespace

from tools.isaac_vr_pose_parity_assay import (
    PoseIdentity,
    PoseParityError,
    PoseThresholds,
    _apply_motion,
    _capture_native,
    _MountedCameraSource,
    _native_articulation,
    _project_fabric_frame,
    _recordables_and_sources,
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


def test_prim_only_zed_recordables_use_configs_and_independent_native_mounts(monkeypatch):
    class Recordable:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def on_session_open(self, stage):
            assert stage == "stage"

    recorder = ModuleType("isaacsim.replicator.episode_recorder")
    for name in ("ArticulationRecordable", "RigidBodyRecordable", "CameraRecordable"):
        setattr(recorder, name, Recordable)
    monkeypatch.setitem(sys.modules, recorder.__name__, recorder)
    roles = ("left_wrist", "right_wrist", "scene")
    configs = [
        SimpleNamespace(prim_path=f"/World/{role}/ZED/Camera", width=960, height=600)
        for role in roles
    ]
    # A 90-degree parent Z rotation plus a 90-degree local X rotation. Expected
    # pose is independent of the recorded Fabric frame and uses xyzw tensors.
    half = np.sqrt(0.5)
    parent_poses = np.array([[[10, 20, 30, 0, 0, half, half]]])
    robots = [
        SimpleNamespace(data=SimpleNamespace(body_link_pose_w=parent_poses.copy())),
        SimpleNamespace(data=SimpleNamespace(body_link_pose_w=np.array([[[0, 0, 0, 0, 0, 0, 1]]]))),
    ]
    left_mount = [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [1, 2, 3, 1]]
    scene_mount = np.eye(4)
    scene_mount[3, :3] = [4, 5, 6]
    mounts = (left_mount, np.eye(4), scene_mount)
    receipts = {
        role: {"prim_path": cfg.prim_path, "desired_optical_matrix": mount}
        for role, cfg, mount in zip(roles, configs, mounts, strict=True)
    }
    env = SimpleNamespace(
        camera=SimpleNamespace(
            wrists=configs[:2], scene_camera=configs[2], live_rgb_enabled=False,
            zed_mounts=receipts,
        ),
        robots=robots, wrist_ids=(0, 0),
        vr_runtime=SimpleNamespace(dynamic_assets=[]), sim=SimpleNamespace(stage="stage"),
    )
    recordables, sources = _recordables_and_sources(env)
    cameras = [item for item in recordables if item.group.startswith("state/camera/")]
    assert [item.prim_path for item in cameras] == [cfg.prim_path for cfg in configs]
    assert all(item.resolution == (960, 600) for item in cameras)
    identities, native = _capture_native(cameras, sources)
    left = native["state/camera/left_wrist"]
    np.testing.assert_allclose(left["position"], [8, 21, 33])
    np.testing.assert_allclose(left["orientation"], [0.5, 0.5, 0.5, 0.5])
    np.testing.assert_array_equal(native["state/camera/scene"]["position"], [4, 5, 6])
    fabric = {group: {key: value.copy() for key, value in frame.items()}
              for group, frame in native.items()}
    assert compare_pose_frame(fabric, native, identities)["passed"]
    # A shifted actual attachment/Fabric pose must fail; it cannot become the
    # oracle just because it was what the recorder observed.
    fabric["state/camera/left_wrist"]["position"][0] += 0.002
    assert not compare_pose_frame(fabric, native, identities)["passed"]
    robots[0].data.body_link_pose_w[0, 0, 0] += 0.1
    _, refreshed = _capture_native(cameras, sources)
    np.testing.assert_allclose(refreshed["state/camera/left_wrist"]["position"], [8.1, 21, 33])
    # Source matrices were copied, so accidental receipt mutation cannot rewrite
    # the expected optical attachment after the assay started.
    receipts["left_wrist"]["desired_optical_matrix"][3][0] += 1
    _, after_receipt_change = _capture_native(cameras, sources)
    np.testing.assert_array_equal(
        after_receipt_change["state/camera/left_wrist"]["position"],
        refreshed["state/camera/left_wrist"]["position"],
    )


@pytest.mark.parametrize("bad_mount", (np.zeros((4, 4)), np.eye(3), np.full((4, 4), np.nan)))
def test_prim_only_camera_oracle_rejects_nonrigid_mount_commands(bad_mount):
    with pytest.raises(PoseParityError, match="rigid"):
        _MountedCameraSource(bad_mount)


def test_prim_only_scene_motion_writes_command_without_sensor_or_pose_readback(monkeypatch):
    # Fake only the USD write seam; SciPy/native oracle remains the real code.
    class Matrix:
        def __init__(self, value):
            self.value = np.asarray(value)

        def GetInverse(self):
            return Matrix(np.linalg.inv(self.value))

        def __mul__(self, other):
            return Matrix(self.value @ other.value)

    writes = []
    attribute = SimpleNamespace(IsValid=lambda: True, Set=lambda value: writes.append(value) or True)
    prim = SimpleNamespace(GetAttribute=lambda name: attribute if name == "xformOp:transform" else None)
    stage = SimpleNamespace(GetPrimAtPath=lambda path: prim if path == "/World/SceneRig" else None)
    pxr = ModuleType("pxr")
    pxr.Gf = SimpleNamespace(Matrix4d=Matrix)
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    mapper = ModuleType("isaac_s1_runtime")
    mapper.d0_action_to_native = lambda target: target
    monkeypatch.setitem(sys.modules, mapper.__name__, mapper)
    commands, advances = [], []
    env = SimpleNamespace(
        home_d0=np.zeros(14), _apply=commands.append, _advance=advances.append,
        vr_runtime=SimpleNamespace(dynamic_assets=[]),
        sim=SimpleNamespace(device="cpu", stage=stage),
        camera=SimpleNamespace(
            scene_camera=SimpleNamespace(prim_path="/World/SceneRig/Camera"),
            zed_mounts={"scene": {"root_path": "/World/SceneRig",
                                  "authored_optical_matrix": np.eye(4).tolist()}},
        ),
    )
    mount = np.eye(4)
    mount[3, :3] = [4, 5, 6]
    source = _MountedCameraSource(mount)
    origin = source.pose_xyzw()
    _apply_motion(env, 1, [], origin, scene_source=source)
    assert advances == [4] and len(commands) == 1
    assert writes[0].value[3, 2] == pytest.approx(6.002)
    np.testing.assert_allclose(source.pose_xyzw()[:3], [4, 5, 6.002])
    # A writer/attachment defect returning the old recorded position is detected.
    recordable = SimpleNamespace(group="camera", prim_path="/World/SceneRig/Camera")
    identities, native = _capture_native((recordable,), {"camera": ("mounted_camera", source)})
    fabric = {"camera": {"position": origin[:3], "orientation": [1, 0, 0, 0]}}
    assert not compare_pose_frame(fabric, native, identities)["passed"]
