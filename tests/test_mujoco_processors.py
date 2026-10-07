"""Unit checks for the D0/native MuJoCo semantic edge."""

from __future__ import annotations

import numpy as np
from lerobot.lerobot_types import TransitionKey

from lerobot_env_piperx_mujoco.constants import JOINT_LIMITS_DEG
from lerobot_env_piperx_mujoco.processors import (
    PiperXMujocoActionProcessor,
    PiperXMujocoObservationProcessor,
)


def test_action_processor_preserves_d0_label_and_reports_saturation() -> None:
    processor = PiperXMujocoActionProcessor()
    d0 = np.asarray(
        [200.0, -10.0, -200.0, 100.0, -100.0, 130.0, 120.0] * 2,
        dtype=np.float64,
    )
    native = processor.action(d0)
    expected_degrees = np.clip(d0[:6], JOINT_LIMITS_DEG[:, 0], JOINT_LIMITS_DEG[:, 1])
    np.testing.assert_allclose(native[:6], np.deg2rad(expected_degrees))
    assert native[6] == 0.1
    np.testing.assert_array_equal(processor.last_d0_action, d0)
    assert processor.last_saturation_mask is not None
    assert processor.last_saturation_mask.all()


def test_action_processor_transition_keeps_dataset_action_separate_from_native_action() -> None:
    processor = PiperXMujocoActionProcessor()
    d0 = np.asarray([-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, -25.0] * 2)
    transition = processor({TransitionKey.ACTION: d0, TransitionKey.INFO: {"source": "test"}})
    np.testing.assert_array_equal(transition[TransitionKey.INFO]["dataset_action_t"], d0)
    assert transition[TransitionKey.INFO]["source"] == "test"
    assert transition[TransitionKey.INFO]["piperx_mujoco_action_saturated"]
    assert transition[TransitionKey.ACTION][6] == 0.0
    assert transition[TransitionKey.ACTION][13] == 0.0


def test_observation_processor_maps_named_native_values_to_exact_d0_order() -> None:
    qpos: dict[str, np.ndarray] = {}
    expected: list[float] = []
    for side_index, side in enumerate(("left", "right")):
        joint_degrees = np.arange(1, 7, dtype=np.float64) + 10 * side_index
        for index, value in enumerate(joint_degrees, start=1):
            qpos[f"{side}_joint{index}"] = np.asarray([np.deg2rad(value)])
        qpos[f"{side}_gripper"] = np.asarray([(-1.0) ** side_index * 0.025])
        expected.extend([*joint_degrees, 25.0])
    left = np.zeros((480, 640, 3), dtype=np.uint8)
    right = np.full((480, 640, 3), 255, dtype=np.uint8)
    result = PiperXMujocoObservationProcessor().observation(
        {"qpos": qpos, "images": {"left_wrist": left, "right_wrist": right}}
    )
    np.testing.assert_allclose(result["observation.state"], expected, atol=1e-5)
    assert result["observation.images.left_wrist"].flags.c_contiguous
    assert result["observation.images.right_wrist"].flags.c_contiguous
