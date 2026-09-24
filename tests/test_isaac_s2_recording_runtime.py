"""Seam checks for the Kit-owned S2 recording transaction order."""

import ast
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import yaml
import numpy as np
import pytest

from tools.isaac_s2_processor import BimanualS2TeleopProcessor, ControllerDeltaSample
from tools.isaac_vr_decision import recordable_teleop_command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import isaac_vr_recording_smoke  # noqa: E402


PROCESSOR_REVISION = "test_processor_revision"


def test_recording_runtime_uses_exact_pre_action_and_successor_boundaries():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    capture = source.index("recording_token = recording.capture_observation()")
    poll = source.index("action = device.advance()", capture)
    apply = source.index("saturated_frames += int(ik.apply(solution))", poll)
    advance = source.index("env._advance(4)", apply)
    successor = source.index("recording.capture_successor(recording_token)", advance)
    causal_commit = source.index("committed = commit_recording_transition(", successor)
    row = source.index("row = build_committed_transition_sample(", causal_commit)
    persist = source.index(
        "recording.commit_transition(recording_token, successor_token, row)", row
    )

    assert capture < poll < apply < advance < successor < causal_commit < row < persist


def test_recording_runtime_declares_offline_profile_and_real_episode_identity():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    metadata_source = (ROOT / "tools/isaac_vr_recording_smoke.py").read_text(encoding="utf-8")
    assert '"source_profile": "isaac_human_vr_offline_rgb_v1"' in metadata_source
    assert 'episode_id = "episode_000000"' in source
    assert "recording.episode_id if recording is not None" in source
    assert "recording.sample(" not in source
    assert 'outcome="unclassified"' not in source


def test_dataset_suspension_follows_snapshot_provenance_and_recordable_setup():
    source = (ROOT / "tools/isaac_vr_recording.py").read_text(encoding="utf-8")
    setup = source.index("def start_live_recording(")
    snapshot = source.index("snapshot = Path(export_stage_snapshot(", setup)
    provenance = source.index("visual_provenance = build_visual_provenance(", snapshot)
    cameras = source.index("CameraRecordable(", provenance)
    opened = source.index("storage, sampler = open_explicit_session(", cameras)
    episode = source.index("start_explicit_episode(", opened)
    suspension = source.index(
        "suspend_dataset_camera_rendering(cameras, stage, camera_roles)", episode
    )
    cadence = source.index("env.render_only_final_substep = True", suspension)
    ready = source.index("return recording", cadence)
    assert snapshot < provenance < cameras < opened < episode < suspension < cadence < ready


def test_physical_recording_hides_backdrop_before_recorder_start():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    prepare = source.index("experiment.prepare_recording_view()")
    start = source.index("recording = start_live_recording(", prepare)
    assert prepare < start

    runtime = (ROOT / "tools/isaac_vr_runtime.py").read_text(encoding="utf-8")
    method = runtime.index("def prepare_recording_view(self)")
    next_method = runtime.index("\n    def ", method + 1)
    body = runtime[method:next_method]
    assert "self.disable_live_rgb()" in body
    assert "self._set_backdrop_visibility(False)" in body


def test_recording_gap_finalizes_episode_before_unrecorded_native_advance():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    discard = source.index(
        "recording.discard_observation(", source.index("if recording is not None and not eligible:")
    )
    continuity_guard = source.index("if recording.committed_frames:", discard)
    finalize = source.index(
        'finalize_recording("operator_stopped", rejection_reason)', continuity_guard
    )
    native_apply = source.index("saturated_frames += int(ik.apply(solution))", finalize)
    assert discard < continuity_guard < finalize < native_apply
    assert "recording_episode_index += 1" in source
    assert '"recording_episodes"' in source
    assert '"left_transition": command.left.transition' in source


def test_record_admission_keeps_safe_solve_and_opposite_arm_motion():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    solution = source.index("solution = _solve_native_decision(")
    gated_apply = source.index("if solution is not None:", solution)
    native_apply = source.index("saturated_frames += int(ik.apply(solution))", gated_apply)
    assert solution < gated_apply < native_apply

    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_solve_native_decision"
    )
    namespace = {}
    exec(compile(ast.Module([node], []), "recording_solve_helper", "exec"), namespace)
    solve = namespace["_solve_native_decision"]

    class FakeIk:
        def __init__(self):
            self.calls = []
            self.applied = []

        def solve(self, command, observation, xr, tick):
            self.calls.append((command, observation, xr, tick))
            return NS(command=command, observation=observation, xr=xr, tick=tick)

        def apply(self, solution):
            self.applied.append(solution)

    ik = FakeIk()
    processor = BimanualS2TeleopProcessor()
    tracked = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
    clutched = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 1.0, 0.0, 0.0)
    untracked = ControllerDeltaSample(np.ones(3), np.ones(3), False, False, 0.0, 0.0, 0.0)
    sequence = (
        (tracked, tracked),  # initial tracking rebase
        (tracked, tracked),  # motion
        (clutched, tracked),  # clutch engaged
        (clutched, tracked),  # clutch held
        (tracked, tracked),  # clutch release rebase
        (tracked, tracked),  # motion resumes
        (untracked, tracked),  # tracking loss
        (tracked, tracked),  # tracking recovery rebase
        (tracked, tracked),  # motion resumes again
    )
    decisions = []
    eligibility = []
    control_tick_id = 0
    for left, right in sequence:
        command = processor.advance(left, right)
        generation = processor.generation
        eligible = recordable_teleop_command(command)
        eligibility.append(eligible)
        if eligible:
            control_tick_id += 1
        observation, xr = object(), object()
        decision = solve(
            ik,
            command,
            observation,
            xr,
            control_tick_id,
            recording_requested=True,
            eligible=eligible,
        )
        decisions.append(decision)
        ik.apply(decision)
        assert processor.generation == generation
        assert decision.command is command
        assert (decision.observation, decision.xr, decision.tick) == (
            (observation, xr, control_tick_id) if eligible else (None, None, None)
        )
    assert eligibility == [
        False,
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        True,
    ]
    assert len(ik.calls) == len(ik.applied) == len(sequence)
    assert control_tick_id == 3
    for decision in decisions[1:]:
        assert np.any(decision.command.right.delta_pose)
    for index in (0, 2, 3, 4, 6, 7):
        np.testing.assert_array_equal(decisions[index].command.left.delta_pose, np.zeros(6))


def test_run_and_rejected_record_have_same_safe_decision():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_solve_native_decision"
    )
    namespace = {}
    exec(compile(ast.Module([node], []), "recording_solve_helper", "exec"), namespace)
    solve = namespace["_solve_native_decision"]

    class FakeIk:
        def __init__(self):
            self.calls = []

        def solve(self, command, observation, xr, tick):
            self.calls.append((command, observation, xr, tick))
            return self.calls[-1]

    processor = BimanualS2TeleopProcessor()
    tracked = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
    clutched = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 1.0, 0.0, 0.0)
    processor.advance(tracked, tracked)
    command = processor.advance(clutched, tracked)
    assert not recordable_teleop_command(command)
    ik = FakeIk()
    run = solve(ik, command, object(), object(), 7, recording_requested=False, eligible=False)
    record = solve(ik, command, object(), object(), 7, recording_requested=True, eligible=False)
    assert run == record == (command, None, None, None)
    assert len(ik.calls) == 2
    assert np.any(run[0].right.delta_pose)


def test_no_client_lifecycle_smoke_captures_and_finalizes_without_teleop(tmp_path, monkeypatch):
    s2_config = tmp_path / "s2.yaml"
    s2_config.write_text(
        yaml.safe_dump(
            {
                "processor": {"revision": PROCESSOR_REVISION},
                "environment": {
                    "isaac_lab_release": "v2.3.0",
                    "cloudxr_runtime_version": "4.0.1",
                },
            }
        )
    )
    s1_config = tmp_path / "s1.yaml"
    s1_config.write_text(
        yaml.safe_dump(
            {
                "environment": {"materialized_path": "/data/runtime/env"},
                "asset": {"source_checkout": "/data/project/assets/source"},
            }
        )
    )
    monkeypatch.setattr(
        isaac_vr_recording_smoke.importlib.metadata,
        "version",
        lambda name: f"{name}-pin",
    )

    calls = []

    class Recording:
        discarded_observations = 0
        episode_id = "episode_000000"
        run_id = "run"
        session_id = "session"

        def capture_observation(self):
            calls.append("capture")
            return "token"

        def discard_observation(self, token, *, reason):
            assert (token, reason) == ("token", "no_client_lifecycle_smoke")
            self.discarded_observations += 1
            calls.append("discard")

        def close(self, *, outcome, reason):
            calls.append(("close", outcome, reason))

    def start(output, env, *, session_metadata, portable_roots):
        calls.append(("start", output, session_metadata, portable_roots))
        return Recording()

    module = ModuleType("isaac_vr_recording")
    module.start_live_recording = start
    monkeypatch.setitem(sys.modules, "isaac_vr_recording", module)
    experiment = NS(
        disable_live_rgb=lambda: calls.append("disable_live_rgb"),
        close=lambda: calls.append("experiment_close"),
    )
    env = NS(
        vr_runtime=experiment,
    )
    report = tmp_path / "report.json"
    args = NS(
        config=s1_config,
        report=report,
        s2_config=s2_config,
        s2_record=True,
        s2_recording_dir=tmp_path / "recording",
        s2_teleop=False,
        xr=False,
    )

    assert (
        isaac_vr_recording_smoke.run_recording_lifecycle_smoke(
            env,
            args,
            default_config_path=s2_config,
            processor_revision=PROCESSOR_REVISION,
        )
        == 0
    )
    assert [call for call in calls if call == "capture"] == ["capture"]
    assert ("close", "aborted", "no_client_lifecycle_smoke") in calls
    result = json.loads(report.read_text())
    assert result["passed"] and not result["teleop_initialized"] and not result["xr_initialized"]


@pytest.mark.parametrize("numbered_root", [False, True])
def test_episode_restart_reuses_session_performance_stream(tmp_path, capsys, numbered_root):
    """Execute production finalization/restart blocks with only storage replaced."""
    from isaac_s2_performance import S2PerformanceLogger

    source = (ROOT / "tools/isaac_s2_runtime.py").read_text()
    tree = ast.parse(source)
    run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_s2")
    finalize = next(
        n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == "finalize_recording"
    )
    # The harness namespace supplies the enclosing run_s2 locals.
    finalize.body[0] = ast.Global(names=["recording", "recording_summary"])
    restart = next(
        n
        for n in ast.walk(run)
        if isinstance(n, ast.If)
        and ast.unparse(n.test) == "recording_requested and recording is None"
    )
    closed, observers = [], []
    log = S2PerformanceLogger(
        tmp_path / "performance.jsonl", window_steps=2, warmup_steps=0, target_hz=30.0
    )
    recordings_root = tmp_path / "recordings" if numbered_root else None
    output = recordings_root / "episode_000000" if numbered_root else tmp_path / "recording"

    def start(path, env, *, session_metadata, portable_roots, timing_observer):
        assert portable_roots["recording"] == path
        observers.append(timing_observer)
        return NS(
            output_dir=path,
            committed_frames=2,
            discarded_observations=1,
            rejections={"operator_hold": 1},
            run_id="run",
            session_id="session",
            episode_id=session_metadata["episode_id"],
            source_profile="isaac_human_vr_offline_rgb_v1",
            close=lambda **kw: closed.append(kw),
        )

    namespace = dict(
        recording=None,
        recording_summary=None,
        recording_episodes=[],
        recording_episode_index=0,
        recording_requested=True,
        args_cli=NS(s2_recording_dir=output, s2_recordings_root=recordings_root),
        env=NS(),
        config_path=ROOT / "config",
        actual_versions={},
        run_id="run",
        session_id="session",
        PROCESSOR_REVISION="test",
        recording_options={"timing_observer": log.add_nested},
        recording_portable_roots=lambda _: {},
        recording_session_metadata=lambda **kw: kw,
        start_live_recording=start,
        Path=Path,
        json=json,
    )
    namespace["recording"] = start(
        output,
        namespace["env"],
        session_metadata={"episode_id": "episode_000000"},
        portable_roots={"recording": output},
        timing_observer=log.add_nested,
    )
    exec(
        compile(ast.fix_missing_locations(ast.Module([finalize], [])), "finalize", "exec"),
        namespace,
    )
    log.begin_step()
    observers[0]("hdf_append_ms", 1000)
    log.end_step(1)
    namespace["finalize_recording"]("operator_stopped", "operator_hold")
    exec(
        compile(ast.fix_missing_locations(ast.Module([restart], [])), "restart", "exec"), namespace
    )
    assert namespace["recording"].output_dir == (
        recordings_root / "episode_000001" if numbered_root else Path(f"{output}-episode_000001")
    )
    assert observers[0].__self__ is observers[1].__self__ is log
    log.begin_step()
    observers[1]("hdf_append_ms", 2000)
    log.end_step(2)
    namespace["finalize_recording"]("operator_stopped", "control_loop_completed")
    exec(
        compile(ast.fix_missing_locations(ast.Module([restart], [])), "restart", "exec"), namespace
    )
    assert namespace["recording"].output_dir == (
        recordings_root / "episode_000002" if numbered_root else Path(f"{output}-episode_000002")
    )
    log.begin_step()
    observers[2]("hdf_append_ms", 3000)
    log.end_step(3)
    namespace["finalize_recording"]("operator_stopped", "control_loop_completed")
    assert len(closed) == len(namespace["recording_episodes"]) == 3
    assert [e["episode_id"] for e in namespace["recording_episodes"]] == [
        "episode_000000",
        "episode_000001",
        "episode_000002",
    ]
    assert log.close()["control"]["samples"] == 3
    events = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert sum(e["event"] == "performance_summary" for e in events) == 1
    assert sum(e["event"] == "performance_step" for e in events) == 3
