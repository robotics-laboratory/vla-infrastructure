"""CPU contract checks for the offline same-input comparison, without Kit/h5py."""
import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_deep/compare_native_recordings.py"
spec = importlib.util.spec_from_file_location("native_recording_parity", SOURCE)
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)


def recording():
    tracks = {}
    for group in ("state/left_robot", "state/right_robot", "state/object_0", "state/object_1",
                  "state/camera/left_wrist", "state/camera/right_wrist", "state/camera/scene"):
        robot = group.endswith("_robot")
        shape = (4, 13) if robot else (4,)
        q = np.zeros(shape + (4,), np.float32)
        q[..., 0] = 1
        tracks[group] = {"positions" if robot else "position": np.zeros(shape + (3,), np.float32),
                         "orientations" if robot else "orientation": q}
        if "/camera/" in group:
            tracks[group].update({key: np.ones(4, np.float32) for key in
                                  ("focal_length", "horizontal_aperture", "vertical_aperture")})
            tracks[group]["clipping_range"] = np.tile([.01, 100.], (4, 1))
    return dict(specs=[dict(group=k) for k in tracks], tracks=tracks,
                relative_steps=np.arange(4) * 4,
                d0={key: np.zeros((3, 14), np.float32) for key in
                    ("dataset_action", "native_clipped", "observation_state", "successor_observation_state")})


def test_all_sources_and_terminal_are_compared():
    left = recording()
    right = copy.deepcopy(left)
    report = parity.compare_loaded(left, right)
    assert report["passed"] and report["initial_state_matched"]
    assert report["all_compared_channels_bit_exact"]
    assert report["observations_including_terminal"] == 4
    right["tracks"]["state/object_1"]["position"][-1, 2] = 2e-6
    report = parity.compare_loaded(left, right)
    assert not report["passed"]
    channel = report["comparisons"]["state/object_1/position"]
    assert channel["first_failed_sample"] == 3 and channel["failed_samples"] == 1
    assert report["initial_state_matched"]


def test_terminal_scalar_recordable_shape_matches_hdf_schema():
    tracks = {"meta/time": {"physics_step": np.array([120, 124])},
              "state/object_0": {"position": np.zeros((2, 3))}}
    terminal = {"meta/time": {"physics_step": np.array([128])},
                "state/object_0": {"position": np.array([1., 2., 3.])}}
    parity.append_terminal(tracks, terminal)
    assert tracks["meta/time"]["physics_step"].tolist() == [120, 124, 128]
    assert tracks["state/object_0"]["position"][-1].tolist() == [1, 2, 3]
    with pytest.raises(ValueError):
        parity.append_terminal(tracks, {**terminal, "meta/time": {"physics_step": [128, 129]}})


@pytest.mark.parametrize("field", ["dataset_action", "native_clipped"])
def test_differing_feedback_commands_or_labels_are_rejected(field):
    left = recording()
    right = copy.deepcopy(left)
    right["d0"][field][-1, -1] = 1e-9
    report = parity.compare_loaded(left, right)
    assert not report["passed"] and not report["same_input_parity_eligible"]
    assert report["same_inputs"][field]["first_differing_row"] == 2
    assert report["same_inputs"][field]["differing_rows"] == 1
    assert report["numeric_differences_are_descriptive_only"]
    assert f"Paired {field} differs" in report["errors"][0]


@pytest.mark.parametrize("field,index", [("observation_state", 13), ("successor_observation_state", 5)])
def test_canonical_state_uses_all_fourteen_channels(field, index):
    left = recording()
    right = copy.deepcopy(left)
    right["d0"][field][0, index] = 2e-5
    report = parity.compare_loaded(left, right)
    assert not report["passed"]
    if field == "observation_state":
        assert not report["initial_state_matched"]


def test_pose_tolerance_and_quaternion_sign_have_explicit_bit_identity():
    left = recording()
    right = copy.deepcopy(left)
    right["tracks"]["state/left_robot"]["positions"][:, 12, 0] = 5e-7
    right["tracks"]["state/camera/scene"]["orientation"] *= -1
    report = parity.compare_loaded(left, right)
    assert report["passed"] and not report["all_compared_channels_bit_exact"]
    assert report["comparisons"]["state/camera/scene/orientation"]["max_abs"] == 0
    with pytest.raises(ValueError, match="Invalid tolerances"):
        parity.compare_loaded(left, right, position_tol=float("nan"))


def test_initial_camera_intrinsics_are_a_prerequisite():
    left = recording()
    right = copy.deepcopy(left)
    right["tracks"]["state/camera/right_wrist"]["focal_length"][0] += .01
    report = parity.compare_loaded(left, right)
    assert not report["initial_state_matched"] and not report["passed"]


@pytest.mark.parametrize("change", ["inventory", "steps", "nonfinite", "missing_pose", "nonunit"])
def test_missing_or_invalid_comparison_evidence_fails(change):
    left = recording()
    right = copy.deepcopy(left)
    if change == "inventory":
        right["specs"][0]["group"] = "another_body"
    elif change == "steps":
        right["relative_steps"][-1] += 1
    elif change == "nonfinite":
        right["tracks"]["state/object_0"]["position"][2, 1] = np.nan
    elif change == "missing_pose":
        del right["tracks"]["state/object_0"]["orientation"]
    else:
        right["tracks"]["state/object_0"]["orientation"][2] = 0
    with pytest.raises(ValueError):
        parity.compare_loaded(left, right)
