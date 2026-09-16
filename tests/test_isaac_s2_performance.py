import math

from tools.isaac_s2_performance import S2PerformanceLogger, _distribution, _percentile


def test_percentile_and_distribution() -> None:
    assert _percentile([], 0.95) == 0.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    summary = _distribution([1.0, 2.0, 3.0, 4.0])
    assert summary["samples"] == 4
    assert summary["mean_ms"] == 2.5
    assert math.isclose(float(summary["p95_ms"]), 3.85)
    assert summary["max_ms"] == 4.0


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

