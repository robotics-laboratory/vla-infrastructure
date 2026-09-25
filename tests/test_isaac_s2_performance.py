import math
import json
from itertools import count

import pytest

from tools.isaac_s2_performance import S2PerformanceLogger, _distribution, _percentile


def test_percentile_and_distribution() -> None:
    assert _percentile([], 0.95) == 0.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    summary = _distribution([1.0, 2.0, 3.0, 4.0])
    assert summary["samples"] == 4
    assert summary["mean_ms"] == 2.5
    assert math.isclose(float(summary["p95_ms"]), 3.85)
    assert summary["max_ms"] == 4.0
    assert math.isclose(float(summary["p99_9_ms"]), 3.997)


def test_logger_writes_steps_windows_and_excludes_warmup(tmp_path) -> None:
    path = tmp_path / "performance.jsonl"
    logger = S2PerformanceLogger(
        path, window_steps=2, warmup_steps=1, target_hz=30.0
    )
    summaries = []
    for step in range(1, 4):
        logger.begin_step()
        with logger.stage("simulation_advance"):
            pass
        logger.add_nested("sim_step", 1_000_000)
        summary = logger.end_step(
            step,
            session_running=True,
            camera_valid=True,
            camera_advanced=True,
        )
        if summary is not None:
            summaries.append(summary)
    final = logger.close()

    assert len(summaries) == 1
    assert summaries[0]["step_first"] == 2
    assert summaries[0]["step_last"] == 3
    assert summaries[0]["nested_stages_not_additive"]["sim_step"]["mean_ms"] == 1.0
    assert final["total_logged_steps"] == 2
    assert final["warmup_steps_excluded"] == 1
    assert final["host_timing_only_no_added_cuda_synchronization"] is True


def test_start_to_start_wall_interval_and_tail_summary(tmp_path, monkeypatch) -> None:
    ticks = count(0, 1_000_000)
    monkeypatch.setattr("tools.isaac_s2_performance.time.perf_counter_ns", lambda: next(ticks))
    logger = S2PerformanceLogger(
        tmp_path / "performance.jsonl", window_steps=10, warmup_steps=1, target_hz=30.0
    )
    for step in range(1, 5):
        logger.begin_step()
        logger.end_step(step)
    summary = logger.close()
    rows = [json.loads(line) for line in logger.path.read_text().splitlines()]
    steps = [row for row in rows if row["event"] == "performance_step"]
    assert steps[0]["start_to_start_ms"] is None
    assert all(row["start_to_start_ms"] == 4.0 for row in steps[1:])
    assert summary["wall_control"]["samples"] == 2
    assert summary["wall_control"]["p99_9_ms"] == 4.0
    assert summary["wall_deadline_miss_fraction"] == 0.0


def test_boundary_event_survives_failure_and_terminal_event(tmp_path) -> None:
    logger = S2PerformanceLogger(
        tmp_path / "performance.jsonl", window_steps=1, warmup_steps=0, target_hz=30.0
    )
    with pytest.raises(RuntimeError, match="seal failed"):
        with logger.boundary("technical_episode_end", reason="tracking_invalid"):
            raise RuntimeError("seal failed")
    logger.record_boundary("terminal_successor_verify", 2_000_000)
    summary = logger.close()
    rows = [json.loads(line) for line in logger.path.read_text().splitlines()]
    assert [row["name"] for row in rows if row["event"] == "performance_boundary"] == [
        "technical_episode_end", "terminal_successor_verify"
    ]
    assert summary["boundaries"]["terminal_successor_verify"]["mean_ms"] == 2.0
