"""Executable tests for the D0 source-time recorder adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from tools.d0_temporal import (
    SourceTiming,
    TemporalContractViolation,
    TemporalFrameRecorder,
    TemporalLimits,
    temporal_feature_specs,
)


ROOT = Path(__file__).resolve().parents[1]


class CapturingDataset:
    def __init__(self, features: dict[str, dict[str, Any]]) -> None:
        self._features = features
        self.frames: list[dict[str, Any]] = []

    @property
    def features(self) -> dict[str, dict[str, Any]]:
        return self._features

    def add_frame(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)


def _contract() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())


def _automated_recorder(dataset: CapturingDataset) -> TemporalFrameRecorder:
    contract = _contract()
    required = tuple(
        contract["dataset"]["temporal_semantics"]["source_timing"][
            "required_feature_sets_by_source_class"
        ]["automated"]
    )
    return TemporalFrameRecorder.from_resolved_contract(
        dataset,
        contract,
        source_class="scripted_expert",
        limits=TemporalLimits(
            max_age_ms={source: 100.0 for source in required},
            max_cross_modal_skew_ms=70.0,
        ),
        accepted_clock_domains=("host_monotonic",),
    )


def _samples(sequence: int = 1) -> dict[str, SourceTiming]:
    return {
        "observation.state": SourceTiming(sequence, 100.030, "host_monotonic"),
        "observation.images.left_wrist": SourceTiming(sequence, 100.000, "host_monotonic"),
        "observation.images.right_wrist": SourceTiming(sequence, 100.010, "host_monotonic"),
        "source_action": SourceTiming(sequence, 100.040, "host_monotonic"),
    }


def test_recorder_persists_source_time_without_overriding_logical_time() -> None:
    contract = _contract()
    timing = contract["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["automated"])
    features = temporal_feature_specs(timing["feature_sets"], required)
    dataset = CapturingDataset(features)
    recorder = _automated_recorder(dataset)

    frame = {"task": "move", "observation.state": np.zeros(14, dtype=np.float32)}
    recorder.add_frame(frame, _samples(), selection_timestamp=100.050)

    assert len(dataset.frames) == 1
    stored = dataset.frames[0]
    assert "timestamp" not in stored
    assert "frame_index" not in stored
    assert stored["temporal.observation.state.sequence"].item() == 1
    assert stored["temporal.observation.state.source_timestamp"].item() == 100.030
    assert stored["temporal.observation.state.clock_domain"] == "host_monotonic"
    assert stored["temporal.observation.state.age_ms"].item() == pytest.approx(20.0)
    assert stored["temporal.cross_modal_skew_ms"].item() == pytest.approx(40.0)
    assert recorder.qa_summary() == {
        "accepted_frames": 1,
        "rejected_frames": 0,
        "rejected_by_reason": {},
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda samples: samples.__setitem__(
                "observation.images.left_wrist",
                SourceTiming(1, 99.900, "host_monotonic"),
            ),
            "stale_source_sample",
        ),
        (
            lambda samples: samples.__setitem__(
                "observation.images.left_wrist",
                SourceTiming(1, 100.000, "camera_device_clock"),
            ),
            "clock_domain_mismatch",
        ),
        (
            lambda samples: samples.__setitem__(
                "source_action",
                SourceTiming(1, 100.060, "host_monotonic"),
            ),
            "future_source_sample",
        ),
    ],
)
def test_invalid_bundle_never_reaches_add_frame(mutation, reason: str) -> None:
    contract = _contract()
    timing = contract["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["automated"])
    dataset = CapturingDataset(temporal_feature_specs(timing["feature_sets"], required))
    recorder = _automated_recorder(dataset)
    samples = _samples()
    mutation(samples)

    with pytest.raises(TemporalContractViolation, match=reason):
        recorder.add_frame({"task": "move"}, samples, selection_timestamp=100.050)

    assert dataset.frames == []
    assert recorder.qa_summary()["rejected_by_reason"] == {reason: 1}


def test_sequence_regression_is_rejected_but_identical_reuse_is_explicit() -> None:
    contract = _contract()
    timing = contract["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["automated"])
    dataset = CapturingDataset(temporal_feature_specs(timing["feature_sets"], required))
    recorder = _automated_recorder(dataset)
    recorder.add_frame({"task": "move"}, _samples(2), selection_timestamp=100.050)
    recorder.add_frame({"task": "move"}, _samples(2), selection_timestamp=100.055)

    with pytest.raises(TemporalContractViolation, match="sequence_regression"):
        recorder.add_frame({"task": "move"}, _samples(1), selection_timestamp=100.060)

    assert len(dataset.frames) == 2


def test_real_lerobot_writer_owns_dense_timestamp_and_persists_source_time(tmp_path: Path) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    contract = _contract()
    timing = contract["dataset"]["temporal_semantics"]["source_timing"]
    required = tuple(timing["required_feature_sets_by_source_class"]["automated"])
    features = {
        "observation.state": {"dtype": "float32", "shape": (1,), "names": ["marker"]},
        "action": {"dtype": "float32", "shape": (1,), "names": ["marker"]},
        **temporal_feature_specs(timing["feature_sets"], required),
    }
    dataset = LeRobotDataset.create(
        repo_id="tests/temporal-contract",
        fps=30,
        features=features,
        root=tmp_path / "dataset",
        use_videos=False,
    )
    recorder = TemporalFrameRecorder.from_resolved_contract(
        dataset,
        contract,
        source_class="scripted_expert",
        limits=TemporalLimits(
            max_age_ms={source: 100.0 for source in required},
            max_cross_modal_skew_ms=70.0,
        ),
        accepted_clock_domains=("host_monotonic",),
    )
    for index in range(2):
        frame = {
            "observation.state": np.asarray([index], dtype=np.float32),
            "action": np.asarray([1000 + index], dtype=np.float32),
            "task": "synthetic",
        }
        samples = {
            name: SourceTiming(index, 100.0 + index / 30, "host_monotonic") for name in required
        }
        recorder.add_frame(frame, samples, selection_timestamp=100.010 + index / 30)
    dataset.save_episode()
    dataset.finalize()

    loaded = LeRobotDataset("tests/temporal-contract", root=tmp_path / "dataset")
    assert loaded[0]["timestamp"].item() == 0.0
    assert loaded[1]["timestamp"].item() == pytest.approx(1 / 30)
    assert loaded[1]["temporal.observation.state.source_timestamp"].item() == pytest.approx(
        100.0 + 1 / 30
    )
    assert loaded[1]["temporal.observation.state.sequence"].item() == 1
