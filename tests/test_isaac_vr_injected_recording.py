"""Deterministic injected-XR recorder seam tests without Kit."""

from pathlib import Path
import hashlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from isaac_s1_runtime import native_state_to_d0  # noqa: E402
from isaac_vr_injected_recording import record_injected_transitions  # noqa: E402
from isaac_vr_recording import (  # noqa: E402
    RecordedObservationToken,
    canonical_committed_transition,
    verify_committed_transition_sample,
)
from tools.isaac_vr_decision import StateSnapshotObservation  # noqa: E402
from tools.isaac_vr_recording_benchmark import (  # noqa: E402
    BenchmarkRunLogger,
    read_benchmark_run,
)


class FakeEnvironment:
    def __init__(self):
        self.physics_step = 20
        self.state = np.asarray(
            [-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0] * 2,
            dtype=np.float32,
        )
        self.pending = None
        self.vr_runtime = SimpleNamespace(config={"scene": {"candidate_home_d0_per_arm": {
            "left": [-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0],
            "right": [-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0],
        }}})

    def _apply(self, targets):
        self.pending = targets

    def _advance(self, repeat):
        assert repeat == 4 and self.pending is not None
        self.physics_step += repeat
        self.state = native_state_to_d0(
            self.pending.left_rad_m,
            self.pending.right_rad_m,
        )
        self.pending = None


class FakeRecording:
    run_id = "injected-run"
    session_id = "injected-session"
    episode_id = "episode_000000"

    def __init__(self, env, timing_observer=None):
        self.env = env
        self.committed_frames = 0
        self.sequence = 0
        self.promoted = None
        self.rows = []
        self.rejections = {}
        self.timing_observer = timing_observer
        self.discarded = []

    def _token(self):
        digest = f"{self.sequence + 1:064x}"
        snapshot_id = f"snapshot-{self.sequence}"
        observation = StateSnapshotObservation(
            1,
            self.env.physics_step,
            self.env.physics_step,
            tuple(float(value) for value in self.env.state),
        ).bind_recording_snapshot(
            capture_sequence=self.sequence,
            snapshot_id=snapshot_id,
            snapshot_sha256=digest,
        )
        token = RecordedObservationToken(
            token_id=self.sequence,
            observation=observation,
            state=observation.state,
            physics_step=observation.physics_step,
            capture_sequence=self.sequence,
            reset_epoch=1,
            state_generation=observation.state_generation,
            scene_state_snapshot_id=snapshot_id,
            scene_state_snapshot_sha256=digest,
        )
        self.sequence += 1
        return token

    def capture_observation(self):
        if self.promoted is not None:
            token, self.promoted = self.promoted, None
            return token
        return self._token()

    def capture_successor(self, token):
        assert token.physics_step + 4 == self.env.physics_step
        return self._token()

    def discard_observation(self, token, *, reason):
        self.discarded.append((token, reason))

    def commit_transition(self, token, successor, row):
        canonical = canonical_committed_transition(row)
        verify_committed_transition_sample(canonical)
        assert int(canonical["frame_index"]) == self.committed_frames
        self.rows.append(canonical)
        if self.timing_observer is not None:
            self.timing_observer("hdf_append_ms", 10)
            self.timing_observer("hdf_flush_ms", 20)
        self.committed_frames += 1
        self.promoted = successor


def test_decision_solver_preserves_preclip_labels_and_applies_clipped_native():
    from tools.isaac_vr_decision import SolvedControlDecision

    env = FakeEnvironment()
    recording = FakeRecording(env)
    decisions, applied = [], []
    original_apply = env._apply

    def solve(command, observation, xr, tick):
        preclip = np.array([0.2, 1.0, -0.5, 0, 0, 0, 0.05] * 2)
        clipped = preclip.copy()
        clipped[0] = 0.1
        decision = SolvedControlDecision.from_native(
            tick, observation, xr, command, preclip, clipped,
        )
        decisions.append(decision)
        return decision

    def apply(target):
        applied.append(target)
        original_apply(target)

    env._apply = apply
    result = record_injected_transitions(
        recording, env, count=2, decision_solver=solve, require_distinct_actions=False,
    )
    assert result["accepted_transactions"] == 2
    for decision, target, row in zip(decisions, applied, recording.rows, strict=True):
        np.testing.assert_array_equal(row["dataset_action"], decision.dataset_action)
        np.testing.assert_array_equal(target.left_rad_m, decision.native_clipped[:7])
        assert target.saturated
        assert decision.native_preclip[0] != target.left_rad_m[0]


@pytest.mark.parametrize("record", [False, True])
@pytest.mark.parametrize("stop_at", ["before", "input_pump", "capture", "transition"])
def test_injected_stop_preserves_only_completed_transitions(tmp_path, monkeypatch, record, stop_at):
    import isaac_vr_injected_recording as injected
    from tools.isaac_s2_performance import S2PerformanceLogger

    env = FakeEnvironment()
    recording = FakeRecording(env)
    logger = S2PerformanceLogger(tmp_path / "performance.jsonl", warmup_steps=0,
                                 window_steps=2, target_hz=30)
    stopped = stop_at == "before"
    pumps = 0
    applied = []
    original_apply, original_advance = env._apply, env._advance
    original_capture = recording.capture_observation

    def pump():
        nonlocal stopped, pumps
        pumps += 1
        if stop_at == "input_pump":
            stopped = True

    def apply(target):
        applied.append(target)
        original_apply(target)

    def advance(repeat):
        nonlocal stopped
        original_advance(repeat)
        if stop_at == "transition":
            stopped = True

    def capture(env=None):
        nonlocal stopped
        token = original_capture() if record else None
        if stop_at == "capture":
            stopped = True
        return token

    env._apply, env._advance = apply, advance
    recording.capture_observation = capture
    monkeypatch.setattr(injected, "capture_state_snapshot", capture)
    kwargs = dict(count=3, performance_logger=logger, input_pump=pump,
                  stop_requested=lambda: stopped)
    try:
        result = (injected.record_injected_transitions(recording, env, **kwargs) if record
                  else injected.run_injected_controls(env, **kwargs))
    finally:
        performance = logger.close()
    completed = int(stop_at == "transition")
    assert result["stopped_by_user"] and not result["completed_control_budget"]
    assert result["requested_control_steps"] == 3
    assert result["input_pump_calls"] == pumps == int(stop_at != "before")
    assert len(applied) == completed
    assert env.physics_step == 20 + 4 * completed
    assert performance["control"]["samples"] == completed
    if record:
        assert result["accepted_transactions"] == result["committed_frames"] == completed
        assert len(recording.rows) == completed
        assert len(recording.discarded) == int(stop_at == "capture")
        if completed:
            assert recording.rows[0]["successor_physics_step"] == env.physics_step
    else:
        assert result["control_steps"] == completed


@pytest.mark.parametrize("count", [3, 330])
def test_injected_transitions_are_distinct_dense_and_self_verifying(count):
    env = FakeEnvironment()
    recording = FakeRecording(env)
    result = record_injected_transitions(recording, env, count=count)

    assert result["accepted_transactions"] == result["committed_frames"] == count
    assert len({tuple(action) for action in result["actions"]}) == count
    assert [int(row["frame_index"]) for row in recording.rows] == list(range(count))
    for current, following in zip(recording.rows, recording.rows[1:], strict=False):
        assert np.array_equal(
            current["successor_observation_state"],
            following["observation_state"],
        )


def test_audit_clutch_rows_hold_left_target_without_segment_split():
    env = FakeEnvironment()
    recording = FakeRecording(env)
    result = record_injected_transitions(
        recording, env, count=108, fixed_input=True, clutch_pattern=True,
        require_distinct_actions=False,
    )
    assert result["left_transition_counts"] == {
        "motion": 102, "clutch_engaged": 1, "clutch_held": 4,
        "clutch_release_rebased": 1,
    }
    assert len(recording.rows) == 108
    for row in recording.rows[100:106]:
        assert np.array_equal(row["dataset_action"][:7], row["observation_state"][:7])


def test_rgb_e2e_injection_commits_clutch_and_distinct_native_states():
    env = FakeEnvironment()
    recording = FakeRecording(env)
    result = record_injected_transitions(recording, env, count=6, rgb_e2e_assay=True)
    assert result["committed_frames"] == 6
    assert bytes(recording.rows[2]["left_transition"]).rstrip(b"\0") == b"clutch_held"
    assert bytes(recording.rows[2]["right_transition"]).rstrip(b"\0") == b"motion"
    assert np.array_equal(
        recording.rows[2]["dataset_action"][:7], recording.rows[2]["observation_state"][:7]
    )
    assert len({tuple(row["observation_state"]) for row in recording.rows}) >= 4


def test_long_periodic_experiment_keeps_all_causal_rows_and_default_guard():
    for strict in (True, False):
        env = FakeEnvironment()
        recording = FakeRecording(env)
        if strict:
            with pytest.raises(RuntimeError, match="actions are not distinct"):
                record_injected_transitions(recording, env, count=1001)
        else:
            result = record_injected_transitions(
                recording, env, count=1001, require_distinct_actions=False
            )
            assert result["accepted_transactions"] == result["committed_frames"] == 1001
            assert result["actions"][0] == result["actions"][1000]
        assert [int(row["frame_index"]) for row in recording.rows] == list(range(1001))


def test_s2_profiling_preserves_causal_rows_and_logs_all_controls(tmp_path):
    import json
    from tools.isaac_s2_performance import S2PerformanceLogger

    logger = S2PerformanceLogger(
        tmp_path / "performance.jsonl", window_steps=2, warmup_steps=1, target_hz=30
    )
    env = FakeEnvironment()
    recording = FakeRecording(env, timing_observer=logger.add_nested)
    result = record_injected_transitions(recording, env, count=3, performance_logger=logger)
    final = logger.close()
    assert result["committed_frames"] == 3
    assert final["control"]["samples"] == 2
    rows = [json.loads(line) for line in logger.path.read_text().splitlines()]
    steps = [row for row in rows if row["event"] == "performance_step"]
    assert len(steps) == 3
    for row in steps:
        assert {
            "observation_capture",
            "injected_decision_apply",
            "simulation_advance",
            "successor_capture",
            "causal_commit_and_record",
        } <= row["stage_ms"].keys()
        assert {"hdf_append_ms", "hdf_flush_ms"} <= row["nested_stage_ms"].keys()


def test_injected_transitions_feed_the_real_benchmark_logger(tmp_path):
    digest = hashlib.sha256(b"fixture").hexdigest()
    identity = {
        "pair_id": "pair",
        "condition": "recording",
        "run_id": "run",
        "git_commit": "a" * 40,
        "dirty_status_sha256": digest,
        "environment_sha256": digest,
        "measurement_provenance_sha256": digest,
        "scene_snapshot_sha256": digest,
        "visual_provenance_sha256": digest,
        "source_profile": "isaac_human_vr_offline_rgb_v2",
        "quest_session_id": "not-applicable:no-headset-injected",
        "target_hz": 30.0,
        "warmup_steps": 1,
        "measured_steps": 2,
        "headset_connected": False,
        "pair_order": 1,
    }
    logger = BenchmarkRunLogger(
        tmp_path / "benchmark.jsonl",
        identity,
        unavailable_timing_metrics=("render_ms", "xr_ms"),
    )
    env = FakeEnvironment()
    recording = FakeRecording(env, timing_observer=logger.add_stage)

    class Resources:
        def sample(self):
            return {
                "process_cpu_percent": 1.0,
                "rss_bytes": 2,
                "gpu_utilization_percent": 3.0,
                "gpu_memory_bytes": 4,
                "disk_read_bytes": 5,
                "disk_write_bytes": 6,
            }

    result = record_injected_transitions(
        recording,
        env,
        count=3,
        benchmark_logger=logger,
        resource_sampler=Resources(),
    )
    artifact = tmp_path / "session.hdf5"
    artifact.write_bytes(b"hdf")
    logger.close(recording_hdf5=artifact)

    run = read_benchmark_run(tmp_path / "benchmark.jsonl")
    assert result["committed_frames"] == 3
    assert run.samples[-1]["counters"]["committed"] == 3
    assert run.samples[-1]["timings_ms"]["hdf_append_ms"] > 0.0
    assert run.samples[-1]["timings_ms"]["hdf_flush_ms"] > 0.0
    assert run.samples[-1]["timing_measurement_status"]["render_ms"] == "not_measured"
