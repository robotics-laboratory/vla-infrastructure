import json

import pytest

from tools.isaac_s2_performance import S2PerformanceLogger
from tools.summarize_vr_performance import main, summarize


def completed_log(tmp_path, warmup=1):
    path = tmp_path / "performance.jsonl"
    logger = S2PerformanceLogger(path, window_steps=2, warmup_steps=warmup, target_hz=30)
    for step in range(1, 4):
        logger.begin_step()
        with logger.stage("simulation_advance"):
            pass
        logger.add_nested("sim_step", 100)
        logger.end_step(step)
    logger.close()
    return path


def test_summary_uses_final_warmup_excluded_distribution(tmp_path, capsys):
    path = completed_log(tmp_path)
    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "samples: 2" in output
    for field in (
        "effective_hz",
        "mean_ms",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
        "deadline_miss_fraction",
    ):
        assert field + ":" in output
    assert "simulation_advance:" in output and "sim_step:" in output
    assert "NON-ADDITIVE" in output
    assert "wall_effective_hz:" in output
    assert "wall_p99_9_ms:" in output
    assert "wall_deadline_miss_fraction:" in output


@pytest.mark.parametrize(
    "fault",
    ["missing", "empty", "malformed", "truncated", "no_samples", "nan", "count", "not_object"],
)
def test_rejects_unusable_logs(tmp_path, fault):
    path = completed_log(tmp_path, warmup=3 if fault == "no_samples" else 1)
    lines = path.read_text().splitlines()
    if fault == "missing":
        path.unlink()
    elif fault == "empty":
        path.write_text("")
    elif fault == "malformed":
        path.write_text("{broken json\n" + "\n".join(lines))
    elif fault == "truncated":
        path.write_text("\n".join(lines[:-1]))
    elif fault == "not_object":
        path.write_text("[]\n")
    elif fault in ("nan", "count"):
        summary = json.loads(lines[-1])
        if fault == "nan":
            summary["effective_hz"] = float("nan")
        else:
            summary["control"]["samples"] += 1
        path.write_text("\n".join([*lines[:-1], json.dumps(summary)]))
    with pytest.raises((OSError, ValueError)):
        summarize(path)
    with pytest.raises(SystemExit) as exc:
        main([str(path)])
    assert exc.value.code == 2
