"""Production-seam tests for temporal recording through LeRobot record_loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from tools.d0_temporal import SourceTiming, temporal_feature_specs
from tools.temporal_recording import wrap_lerobot_dataset_for_temporal_recording


ROOT = Path(__file__).resolve().parents[1]


class ScriptedClock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class TimedRobot:
    name = "timed_test_robot"

    def __init__(self) -> None:
        self.sequence = 0
        self.sent_actions: list[dict[str, float]] = []

    def get_observation(self) -> dict[str, Any]:
        self.sequence += 1
        return {
            "marker": float(self.sequence),
            "left_wrist": np.full((2, 2, 3), 17, dtype=np.uint8),
            "right_wrist": np.full((2, 2, 3), 23, dtype=np.uint8),
        }

    def latest_observation_timing(self) -> dict[str, SourceTiming]:
        return {
            "observation.state": SourceTiming(self.sequence, 100.030, "host_monotonic"),
            "observation.images.left_wrist": SourceTiming(self.sequence, 100.000, "host_monotonic"),
            "observation.images.right_wrist": SourceTiming(
                self.sequence, 100.010, "host_monotonic"
            ),
        }

    def send_action(self, action: dict[str, float]) -> dict[str, float]:
        self.sent_actions.append(action)
        return action


class TestTeleoperator:
    action_features = {"marker": float}
    feedback_features: dict[str, type] = {}
    is_connected = True
    is_calibrated = True

    def connect(self, calibrate: bool = True) -> None:
        del calibrate

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        pass

    def get_action(self) -> dict[str, float]:
        return {"marker": 1001.0}

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        del feedback

    def disconnect(self) -> None:
        self.is_connected = False


def _contract() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())


def test_upstream_record_loop_writes_temporal_features_before_add_frame(tmp_path: Path) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.processor import make_default_processors
    from lerobot.scripts.lerobot_record import record_loop

    contract = _contract()
    timing = contract["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["automated"])
    action_spec = {"dtype": "float32", "shape": (1,), "names": ["marker"]}
    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (1,),
            "names": ["marker"],
        },
        "observation.images.left_wrist": {"dtype": "image", "shape": (2, 2, 3)},
        "observation.images.right_wrist": {"dtype": "image", "shape": (2, 2, 3)},
        "action": action_spec,
        **temporal_feature_specs(timing["feature_sets"], required),
    }
    dataset = LeRobotDataset.create(
        repo_id="tests/temporal-production-path",
        fps=30,
        features=features,
        root=tmp_path / "dataset",
        use_videos=False,
    )
    robot = TimedRobot()
    adapter, teleop = wrap_lerobot_dataset_for_temporal_recording(
        dataset,
        contract,
        robot=robot,
        teleop=TestTeleoperator(),
        source_class="scripted_expert",
        monotonic=ScriptedClock(100.040, 100.050),
    )
    teleop_processor, robot_action_processor, observation_processor = make_default_processors()

    record_loop(
        robot=robot,
        events={"exit_early": False},
        fps=30,
        teleop_action_processor=teleop_processor,
        robot_action_processor=robot_action_processor,
        robot_observation_processor=observation_processor,
        dataset=adapter,
        teleop=teleop,
        control_time_s=0.001,
        single_task="synthetic",
    )
    adapter.save_episode()
    dataset.finalize()

    loaded = LeRobotDataset(
        "tests/temporal-production-path",
        root=tmp_path / "dataset",
    )
    assert len(loaded) == 1
    assert loaded[0]["timestamp"].item() == 0.0
    assert loaded[0]["temporal.observation.images.left_wrist.source_timestamp"].item() == 100.0
    assert loaded[0][
        "temporal.observation.images.right_wrist.source_timestamp"
    ].item() == pytest.approx(100.01)
    assert loaded[0]["temporal.source_action.source_timestamp"].item() == pytest.approx(100.04)
    assert loaded[0]["temporal.cross_modal_skew_ms"].item() == pytest.approx(40.0)
    assert features["action"] == action_spec
    assert robot.sent_actions == [{"marker": 1001.0}]


def test_human_vr_recording_fails_fast_without_xr_acquisition_timing(tmp_path: Path) -> None:
    class Dataset:
        fps = 30
        features: dict[str, dict[str, Any]] = {}

    with pytest.raises(ValueError, match="XR acquisition-timing provider"):
        wrap_lerobot_dataset_for_temporal_recording(
            Dataset(),
            _contract(),
            robot=TimedRobot(),
            teleop=TestTeleoperator(),
            source_class="human_vr",
            pose_timing_reader=None,
            monotonic=ScriptedClock(),
        )
