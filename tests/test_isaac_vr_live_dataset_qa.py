"""Fail-closed row/pixel checks; real LeRobot CPU benchmarks are retained separately."""

import hashlib

import numpy as np
import pytest

from tools import isaac_vr_live_dataset_qa as qa
from test_isaac_vr_lerobot_materialize import _arrays

torch = pytest.importorskip("torch")
upstream = pytest.importorskip("lerobot.datasets.lerobot_dataset")
SHAPE = (4, 6, 3)


class FakeDataset:
    def __init__(self, arrays, *, return_uint8=False, fault=None):
        self.arrays, self.uint8, self.fault = arrays, return_uint8, fault
        self.features = qa.common.canonical_lerobot_features(SHAPE)

    def __len__(self):
        return len(self.arrays["frame_index"])

    def __getitem__(self, index):
        item = {
            "observation.state": torch.from_numpy(self.arrays["observation_state"][index].copy()),
            "action": torch.from_numpy(self.arrays["action"][index].copy()),
            "frame_index": torch.tensor(index),
            "index": torch.tensor(index),
            "episode_index": torch.tensor(0),
            "task_index": torch.tensor(0),
            "timestamp": torch.tensor(index / qa.common.FPS, dtype=torch.float32),
            "task": "fixture task",
        }
        for role_id, role in enumerate(qa.common.CAMERA_ROLES):
            image = torch.full((3, SHAPE[0], SHAPE[1]), 20 + index + role_id, dtype=torch.uint8)
            item[f"observation.images.{role}"] = image if self.uint8 else image.float() / 255
        if index == 1 and self.fault:
            if self.fault in (
                "action",
                "timestamp",
                "frame_index",
                "index",
                "episode_index",
                "task_index",
            ):
                item[self.fault] += 1
            elif self.fault == "task":
                item["task"] = "wrong task"
            elif self.fault == "pixel":
                item["observation.images.scene"][0, 0, 0] = 0
            elif self.fault == "float" and not self.uint8:
                item["observation.images.scene"] += 0.01
        return item


def _inputs(monkeypatch, fault=None):
    arrays = _arrays(4)
    monkeypatch.setattr(
        upstream,
        "LeRobotDataset",
        lambda *args, **kwargs: FakeDataset(
            arrays, return_uint8=kwargs.get("return_uint8", False), fault=fault
        ),
    )
    hashes = {
        f"observation.images.{role}": [
            hashlib.sha256(np.full(SHAPE, 20 + i + role_id, np.uint8).tobytes()).hexdigest()
            for i in range(4)
        ]
        for role_id, role in enumerate(qa.common.CAMERA_ROLES)
    }
    return dict(
        root="unused",
        repo_id="fixture/qa",
        arrays=arrays,
        task="fixture task",
        decoded_rgb_sha256=hashes,
        image_shape=SHAPE,
    )


def test_one_full_pass_checks_labels_pixels_and_float_contract(monkeypatch):
    previous = torch.get_num_threads()
    result = qa.qa_live_dataset(**_inputs(monkeypatch))
    assert result["all_frames_read"] == 4 and result["all_video_frames_decoded"] == 12
    assert result["float_sample_rows"] == [0, 1, 2, 3]
    assert result["float_video_frames_decoded"] == 12
    assert result["rgb_fingerprints_verified"] and result["passes"] == 1
    assert torch.get_num_threads() == previous


@pytest.mark.parametrize(
    "fault",
    [
        "action",
        "timestamp",
        "frame_index",
        "index",
        "episode_index",
        "task_index",
        "task",
        "pixel",
        "float",
    ],
)
def test_changed_row_or_pixels_fail(monkeypatch, fault):
    previous = torch.get_num_threads()
    with pytest.raises(qa.common.MaterializationError):
        qa.qa_live_dataset(**_inputs(monkeypatch, fault))
    assert torch.get_num_threads() == previous


@pytest.mark.parametrize("fault", ["camera", "count", "digest", "worker", "source_action"])
def test_invalid_expected_inputs_fail(monkeypatch, fault):
    inputs = _inputs(monkeypatch)
    hashes = inputs["decoded_rgb_sha256"]
    if fault == "camera":
        del hashes[next(iter(hashes))]
    elif fault == "count":
        hashes[next(iter(hashes))].pop()
    elif fault == "digest":
        hashes[next(iter(hashes))][0] = "not sha256"
    elif fault == "worker":
        inputs["workers"] = 1
    else:
        inputs["arrays"]["action"][0, 0] = np.nan
    with pytest.raises(qa.common.MaterializationError):
        qa.qa_live_dataset(**inputs)
