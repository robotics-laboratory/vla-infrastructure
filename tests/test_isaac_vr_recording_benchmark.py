import copy
import hashlib
import json

import pytest

from tools.isaac_vr_recording_benchmark import (
    BenchmarkRunLogger,
    REQUIRED_THRESHOLD_PATHS,
    THRESHOLD_SCHEMA_VERSION,
    build_paired_report,
    read_benchmark_run,
    validate_paired_report,
)
from tools.isaac_vr_recording_smoke import _nvml_resource_sampler


def _identity(condition: str, *, pair_id: str = "pair-1", headset: bool = True) -> dict:
    digest = hashlib.sha256(b"fixture").hexdigest()
    return {
        "pair_id": pair_id,
        "condition": condition,
        "run_id": f"{pair_id}-{condition}",
        "git_commit": "a" * 40,
        "dirty_status_sha256": digest,
        "environment_sha256": digest,
        "measurement_provenance_sha256": digest,
        "scene_snapshot_sha256": digest,
        "visual_provenance_sha256": digest,
        "source_profile": "isaac_human_vr_offline_rgb_v1",
        "quest_session_id": f"quest-{pair_id}",
        "target_hz": 30.0,
        "warmup_steps": 1,
        "measured_steps": 3,
        "headset_connected": headset,
        "pair_order": 1 if condition == "baseline" else 2,
    }


def _write_run(
    tmp_path,
    condition: str,
    *,
    pair_id: str = "pair-1",
    headset: bool = True,
    unavailable_timing_metrics=(),
):
    path = tmp_path / f"{pair_id}-{condition}.jsonl"
    logger = BenchmarkRunLogger(
        path,
        _identity(condition, pair_id=pair_id, headset=headset),
        unavailable_timing_metrics=unavailable_timing_metrics,
    )
    for step in range(1, 5):
        logger.begin_step(step)
        logger.add_stage("state_sampling_ms", (1_000_000 if condition == "baseline" else 1_200_000))
        if "render_ms" not in unavailable_timing_metrics:
            logger.add_stage("render_ms", (4_000_000 if condition == "baseline" else 4_200_000))
        if "xr_ms" not in unavailable_timing_metrics:
            logger.add_stage("xr_ms", (2_000_000 if condition == "baseline" else 2_100_000))
        if condition == "recording":
            logger.add_stage("hdf_append_ms", 500_000)
            if step == 4:
                logger.add_stage("hdf_flush_ms", 800_000)
        logger.end_step(
            resources={
                "process_cpu_percent": 50.0 + (5.0 if condition == "recording" else 0.0),
                "rss_bytes": 1_000_000 + (100_000 if condition == "recording" else 0),
                "gpu_utilization_percent": 70.0 + (2.0 if condition == "recording" else 0.0),
                "gpu_memory_bytes": 2_000_000 + (200_000 if condition == "recording" else 0),
                "disk_read_bytes": step * 10,
                "disk_write_bytes": step * (100 if condition == "recording" else 10),
            },
            committed=step,
            rejected=0,
            dropped=0,
            deadline_missed=False,
        )
    artifact = None
    if condition == "recording":
        artifact = tmp_path / f"{pair_id}-session.hdf5"
        artifact.write_bytes(b"hdf" * 1000)
    logger.close(recording_hdf5=artifact)
    return path


def _thresholds(value: float = 1e15) -> dict:
    return {
        "schema": THRESHOLD_SCHEMA_VERSION,
        "minimum_pairs": 1,
        "minimum_steps_per_run": 3,
        "limits": {path: value for path in REQUIRED_THRESHOLD_PATHS},
    }


def test_paired_report_retains_required_metrics_and_pending_status(tmp_path) -> None:
    baseline = _write_run(tmp_path, "baseline")
    recording = _write_run(tmp_path, "recording")

    report = build_paired_report([recording, baseline])

    assert report["pair_count"] == 1
    assert report["physical_quest_pair_count"] == 1
    assert report["qualification"]["status"] == "threshold_pending"
    assert report["recording"]["timings"]["hdf_append_ms"]["p95_ms"] == 0.5
    assert report["recording"]["timings"]["hdf_flush_ms"]["p99_ms"] > 0.0
    assert report["recording"]["outcomes"]["committed"] == 3
    assert report["recording"]["disk"]["artifact_bytes_per_committed_frame"] == 1000
    assert set(report["overhead"]["timings"]) == {
        "control_loop_ms",
        "state_sampling_ms",
        "render_ms",
        "xr_ms",
    }
    validate_paired_report(report)


def test_complete_threshold_policy_passes_and_one_exceeded_limit_fails(tmp_path) -> None:
    paths = [_write_run(tmp_path, "baseline"), _write_run(tmp_path, "recording")]
    policy = _thresholds()
    passed = build_paired_report(paths, threshold_policy=policy)
    assert passed["qualification"]["status"] == "passed"

    strict = _thresholds()
    strict["limits"]["recording.outcomes.drop_fraction"] = 0.0
    strict["limits"]["overhead.resources.rss_bytes.max_delta"] = 1.0
    failed = build_paired_report(paths, threshold_policy=strict)
    assert failed["qualification"]["status"] == "failed"
    assert any(
        check["metric"] == "overhead.resources.rss_bytes.max_delta" and not check["passed"]
        for check in failed["qualification"]["checks"]
    )


def test_incomplete_threshold_policy_fails_closed(tmp_path) -> None:
    paths = [_write_run(tmp_path, "baseline"), _write_run(tmp_path, "recording")]
    policy = _thresholds()
    policy["limits"].pop("recording.outcomes.drop_fraction")
    with pytest.raises(ValueError, match="threshold coverage must be exact"):
        build_paired_report(paths, threshold_policy=policy)


def test_pairing_provenance_mismatch_is_rejected(tmp_path) -> None:
    baseline = _write_run(tmp_path, "baseline")
    recording = _write_run(tmp_path, "recording")
    rows = [json.loads(line) for line in recording.read_text().splitlines()]
    rows[0]["identity"]["scene_snapshot_sha256"] = "c" * 64
    recording.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    with pytest.raises(ValueError, match="provenance mismatch: scene_snapshot_sha256"):
        build_paired_report([baseline, recording])


def test_raw_and_derived_mutations_are_detected(tmp_path) -> None:
    baseline = _write_run(tmp_path, "baseline")
    recording = _write_run(tmp_path, "recording")
    report = build_paired_report([baseline, recording])
    mutated = copy.deepcopy(report)
    mutated["recording"]["outcomes"]["dropped"] = 1
    with pytest.raises(ValueError, match="self-hash mismatch"):
        validate_paired_report(mutated)

    baseline.write_text(baseline.read_text() + "\n")
    with pytest.raises(ValueError, match="raw benchmark evidence hash mismatch"):
        validate_paired_report(report)


def test_bound_recording_artifact_mutation_is_detected(tmp_path) -> None:
    recording = _write_run(tmp_path, "recording")
    (tmp_path / "pair-1-session.hdf5").write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact size changed"):
        read_benchmark_run(recording)


def test_pair_order_must_be_complementary(tmp_path) -> None:
    baseline = _write_run(tmp_path, "baseline")
    recording = _write_run(tmp_path, "recording")
    rows = [json.loads(line) for line in recording.read_text().splitlines()]
    rows[0]["identity"]["pair_order"] = 1
    recording.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="complementary pair_order"):
        build_paired_report([baseline, recording])


def test_headless_pair_is_analyzable_but_cannot_qualify(tmp_path) -> None:
    paths = [
        _write_run(tmp_path, "baseline", headset=False),
        _write_run(tmp_path, "recording", headset=False),
    ]
    report = build_paired_report(paths)
    assert report["physical_quest_pair_count"] == 0
    assert report["qualification"]["status"] == "failed"
    assert report["qualification"]["threshold_status"] == "threshold_pending"


def test_unavailable_render_and_xr_are_explicit_and_never_qualify(tmp_path) -> None:
    unavailable = ("render_ms", "xr_ms")
    paths = [
        _write_run(
            tmp_path,
            "baseline",
            headset=False,
            unavailable_timing_metrics=unavailable,
        ),
        _write_run(
            tmp_path,
            "recording",
            headset=False,
            unavailable_timing_metrics=unavailable,
        ),
    ]

    report = build_paired_report(paths, threshold_policy=_thresholds())

    assert report["measurement_completeness"] == {
        "complete": False,
        "unavailable_timing_metrics": ["render_ms", "xr_ms"],
    }
    assert report["overhead"]["timings"]["render_ms"]["measurement_status"] == "not_measured"
    assert report["qualification"]["status"] == "failed"
    assert report["qualification"]["threshold_status"] == "not_evaluated"


def test_unavailable_stage_cannot_receive_a_measurement(tmp_path) -> None:
    logger = BenchmarkRunLogger(
        tmp_path / "raw.jsonl",
        _identity("recording"),
        unavailable_timing_metrics=("render_ms",),
    )
    logger.begin_step(1)
    with pytest.raises(ValueError, match="declared unavailable"):
        logger.add_stage("render_ms", 1)


def test_resource_sampler_uses_persistent_nvml_library_without_python_binding(
    monkeypatch,
) -> None:
    calls = []

    class Library:
        def nvmlInit_v2(self):
            calls.append("init")
            return 0

        def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
            assert index.value == 0
            handle._obj.value = 123
            return 0

        def nvmlDeviceGetUtilizationRates(self, handle, utilization):
            assert handle.value == 123
            utilization._obj.gpu = 47
            utilization._obj.memory = 9
            return 0

        def nvmlDeviceGetMemoryInfo(self, handle, memory):
            assert handle.value == 123
            memory._obj.used = 456
            return 0

        def nvmlShutdown(self):
            calls.append("shutdown")
            return 0

    monkeypatch.setattr("tools.isaac_vr_recording_smoke.ctypes.CDLL", lambda _: Library())
    sampler, shutdown = _nvml_resource_sampler()

    sample = sampler.sample()
    shutdown()

    assert sample["gpu_utilization_percent"] == 47.0
    assert sample["gpu_memory_bytes"] == 456
    assert calls == ["init", "shutdown"]


def test_baseline_cannot_claim_hdf_work(tmp_path) -> None:
    path = tmp_path / "bad-baseline.jsonl"
    logger = BenchmarkRunLogger(path, _identity("baseline"))
    logger.begin_step(1)
    logger.add_stage("hdf_append_ms", 1)
    with pytest.raises(ValueError, match="baseline run cannot contain HDF"):
        logger.end_step(
            resources={
                name: 0.0
                for name in (
                    "process_cpu_percent",
                    "rss_bytes",
                    "gpu_utilization_percent",
                    "gpu_memory_bytes",
                    "disk_read_bytes",
                    "disk_write_bytes",
                )
            },
            committed=0,
            rejected=0,
            dropped=0,
            deadline_missed=False,
        )


def test_reader_rejects_partial_log(tmp_path) -> None:
    path = tmp_path / "partial.jsonl"
    logger = BenchmarkRunLogger(path, _identity("recording"))
    logger.begin_step(1)
    logger.add_stage("state_sampling_ms", 1)
    logger.end_step(
        resources={
            name: 0.0
            for name in (
                "process_cpu_percent",
                "rss_bytes",
                "gpu_utilization_percent",
                "gpu_memory_bytes",
                "disk_read_bytes",
                "disk_write_bytes",
            )
        },
        committed=1,
        rejected=0,
        dropped=0,
        deadline_missed=False,
    )
    logger._stream.flush()
    with pytest.raises(ValueError, match="incomplete benchmark log"):
        read_benchmark_run(path)
