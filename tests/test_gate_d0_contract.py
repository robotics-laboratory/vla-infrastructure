"""Gate D0 semantic and same-tick causality regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from lerobot.processor.factory import make_default_processors
from lerobot.utils.constants import ACTION, OBS_STR
from lerobot.utils.feature_utils import (
    build_dataset_frame,
    combine_feature_dicts,
    hw_to_dataset_features,
)

from tools.validate_resolved_contract import canonical_training_schema_fingerprint


ROOT = Path(__file__).resolve().parents[1]


def assert_same_tick_pairs(pairs: list[tuple[int, int]]) -> None:
    assert pairs == [(tick, 1000 + tick) for tick in range(len(pairs))]


def test_record_loop_frame_seam_preserves_obs_t_action_t() -> None:
    """Exercise the exact processor/build_dataset_frame seam used by record_loop."""
    features = combine_feature_dicts(
        hw_to_dataset_features({"marker": float}, OBS_STR, use_video=False),
        hw_to_dataset_features({"marker": float}, ACTION, use_video=False),
    )
    teleop_processor, runtime_processor, observation_processor = make_default_processors()
    frames: list[dict] = []
    runtime_commands: list[dict[str, float]] = []
    send_action_returns: list[dict[str, float]] = []

    for tick in range(4):
        # These statements intentionally mirror pinned lerobot_record.record_loop:289-338.
        observation_t = {"marker": float(tick)}
        processed_observation_t = observation_processor(observation_t)
        source_action_t = {"marker": float(1000 + tick)}
        dataset_action_t = teleop_processor((source_action_t, observation_t))
        runtime_command_t = runtime_processor((dataset_action_t, observation_t))
        runtime_commands.append(runtime_command_t)
        # Deliberately different: the send_action return must not become dataset.action.
        send_action_returns.append({"marker": runtime_command_t["marker"] + 50_000.0})
        frames.append(
            {
                **build_dataset_frame(features, processed_observation_t, prefix=OBS_STR),
                **build_dataset_frame(features, dataset_action_t, prefix=ACTION),
                "task": "synthetic same-tick task",
            }
        )

    pairs = [
        (
            int(frame["observation.state"].item()),
            int(frame["action"].item()),
        )
        for frame in frames
    ]
    assert_same_tick_pairs(pairs)
    assert [int(action["marker"]) for action in runtime_commands] == [1000, 1001, 1002, 1003]
    assert [int(action["marker"]) for action in send_action_returns] == [51000, 51001, 51002, 51003]


def test_causality_oracle_rejects_both_off_by_one_directions() -> None:
    with pytest.raises(AssertionError):
        assert_same_tick_pairs([(0, 999), (1, 1000), (2, 1001)])
    with pytest.raises(AssertionError):
        assert_same_tick_pairs([(0, 1001), (1, 1002), (2, 1003)])


def test_d0_contract_matches_upstream_processors_and_fingerprint() -> None:
    contract = yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (ROOT / "artifacts/gate_d0/upstream_processor_snapshot.json").read_text(encoding="utf-8")
    )
    processors = make_default_processors()
    assert [processor.get_config() for processor in processors] == [
        snapshot["pipelines"]["teleop_action_processor"],
        snapshot["pipelines"]["robot_action_processor"],
        snapshot["pipelines"]["robot_observation_processor"],
    ]
    assert all(processor.state_dict() == {} for processor in processors)
    assert contract["dataset"]["common_training_view"]["schema_fingerprint_sha256"] == (
        canonical_training_schema_fingerprint(contract)
    )


def temporal_bundle_is_admissible(
    selection_timestamp: float,
    sources: dict[str, dict],
    max_age_ms: dict[str, float],
    max_cross_modal_skew_ms: float,
) -> bool:
    """Small D0 oracle: logical dataset time is intentionally not an input."""
    domains = {sample["clock_domain"] for sample in sources.values()}
    if len(domains) != 1:
        return False
    source_timestamps = [sample["source_timestamp"] for sample in sources.values()]
    ages_ms = {
        name: (selection_timestamp - sample["source_timestamp"]) * 1000
        for name, sample in sources.items()
    }
    if any(age < 0 or age > max_age_ms[name] for name, age in ages_ms.items()):
        return False
    skew_ms = (max(source_timestamps) - min(source_timestamps)) * 1000
    return skew_ms <= max_cross_modal_skew_ms


def test_source_freshness_is_independent_of_logical_dataset_timestamp() -> None:
    contract = yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text(encoding="utf-8"))
    temporal = contract["dataset"]["temporal_semantics"]
    dataset_timestamp = 105 / contract["timing"]["dataset_fps"]
    assert dataset_timestamp == 3.5
    assert temporal["dataset_timestamp"]["freshness_eligible"] is False

    sources = {
        "joint": {"sequence": 205, "source_timestamp": 1003.480, "clock_domain": "host_monotonic"},
        "camera": {"sequence": 91, "source_timestamp": 1003.420, "clock_domain": "host_monotonic"},
        "xr": {"sequence": 104, "source_timestamp": 1003.470, "clock_domain": "host_monotonic"},
    }
    limits = {"joint": 40.0, "camera": 100.0, "xr": 40.0}
    assert temporal_bundle_is_admissible(1003.500, sources, limits, 70.0)

    stale_camera = {name: dict(sample) for name, sample in sources.items()}
    stale_camera["camera"]["source_timestamp"] = 1003.379
    assert not temporal_bundle_is_admissible(1003.500, stale_camera, limits, 130.0)


def test_cross_modal_skew_and_clock_domain_are_fail_closed() -> None:
    sources = {
        "joint": {"sequence": 10, "source_timestamp": 50.000, "clock_domain": "host_monotonic"},
        "camera": {"sequence": 7, "source_timestamp": 49.940, "clock_domain": "host_monotonic"},
    }
    limits = {"joint": 100.0, "camera": 100.0}
    assert not temporal_bundle_is_admissible(50.010, sources, limits, 50.0)

    sources["camera"]["source_timestamp"] = 50.000
    sources["camera"]["clock_domain"] = "device_unsynchronized"
    assert not temporal_bundle_is_admissible(50.010, sources, limits, 50.0)
