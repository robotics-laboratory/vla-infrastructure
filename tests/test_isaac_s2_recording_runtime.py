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
    assert '"source_profile": "isaac_human_vr_offline_rgb_v2"' in metadata_source
    assert 'episode_id = f"episode_{recording_episode_index:06d}"' in source
    assert "recording.episode_id if recording is not None" in source
    assert "recording.sample(" not in source
    assert 'outcome="unclassified"' not in source


def test_recording_setup_preserves_ffft_and_uses_prim_state_without_rtx_resources():
    source = (ROOT / "tools/isaac_vr_recording.py").read_text(encoding="utf-8")
    setup = source.index("def start_live_recording(")
    body = source[setup:source.index("def _sanitize_exported_stage(", setup)]
    assert "env.camera.camera_prim_paths" in body
    assert 'getattr(camera, "_render_data", None)' in body
    assert "suspend_dataset_camera_rendering" not in body
    assert "render_only_final_substep" not in body
    assert "render_substeps =" not in body
    assert "CameraRecordable(" in body


def test_physical_recording_preserves_selected_backdrop_without_camera_rgb():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    prepare = source.index("experiment.prepare_recording_view()")
    start = source.index("recording = start_live_recording(", prepare)
    assert prepare < start

    runtime = (ROOT / "tools/isaac_vr_runtime.py").read_text(encoding="utf-8")
    method = runtime.index("def prepare_recording_view(self)")
    next_method = runtime.index("\n    def ", method + 1)
    body = runtime[method:next_method]
    assert "self.disable_live_rgb()" in body
    assert 'self._set_backdrop_visibility(bool(self.config["scene"]["backdrop"]["initial_visibility"]))' in body


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
    assert "recording = recording_session.start_episode(output_dir, episode_id)" in source
    assert source.count("recording = start_live_recording(") == 1
    assert '"recording_episodes"' in source
    assert '"left_transition": command.left.transition' in source


def test_record_lifecycle_gates_episode_opening_and_menu_ticks():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    poll = source.index("action = device.advance()")
    lifecycle_input = source.index("event = lifecycle.buttons(", poll)
    start_episode = source.index("recording = start_live_recording(", lifecycle_input)
    eligibility = source.index("eligible = (", lifecycle_input)
    assert poll < lifecycle_input < eligibility < start_episode
    assert "lifecycle.admits_recording and eligible and recording is None" in source
    assert '"success", "failure", "incomplete")' in source
    assert "RecordingState.CLASSIFY_OUTCOME" in source
    assert "lifecycle.disconnect()" in source
    assert '"isaac_human_vr_offline_rgb_v2"' in source
    assert 'recenter_control="right_thumbstick_click"' in source
    upstream = (ROOT / "tools/isaac_s2_upstream.py").read_text(encoding="utf-8")
    assert "RECORD_STOP_BUTTON_INDEX = 25" in upstream
    assert 'record_stop_control="left_secondary_click"' in source


def test_record_admission_keeps_safe_solve_and_opposite_arm_motion():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    solution = source.index("solution = _solve_native_decision(")
    gated_apply = source.index("if solution is not None:", solution)
    native_apply = source.index("saturated_frames += int(ik.apply(solution))", gated_apply)
    assert solution < gated_apply < native_apply
    epoch_gap = source.index('finalize_recording("operator_stopped", "causal_epoch_changed")')
    assert "solution = None" not in source[epoch_gap:native_apply]

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
        True,
        True,
        True,
        True,
        False,
        False,
        True,
    ]
    assert len(ik.calls) == len(ik.applied) == len(sequence)
    assert control_tick_id == 6
    for decision in decisions[1:]:
        assert np.any(decision.command.right.delta_pose)
    for index in (0, 2, 3, 4, 6, 7):
        np.testing.assert_array_equal(decisions[index].command.left.delta_pose, np.zeros(6))


def test_clutch_rows_keep_one_episode_and_tracking_gap_starts_another():
    processor = BimanualS2TeleopProcessor()
    motion = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
    clutch = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 1.0, 0.0, 0.0)
    lost = ControllerDeltaSample(np.ones(3), np.ones(3), False, False, 0.0, 0.0, 0.0)

    class FakeIk:
        def __init__(self):
            self.applied = []

        def solve(self, command, observation, xr, tick):
            return NS(command=command, observation=observation, xr=xr, tick=tick,
                      native_target=tuple(command.left.delta_pose) + tuple(command.right.delta_pose))

        def apply(self, decision):
            self.applied.append(decision)

    node = next(node for node in ast.parse(
        (ROOT / "tools/isaac_s2_runtime.py").read_text()
    ).body if isinstance(node, ast.FunctionDef) and node.name == "_solve_native_decision")
    namespace = {}
    exec(compile(ast.Module([node], []), "recording_solve_helper", "exec"), namespace)
    solve = namespace["_solve_native_decision"]
    ik = FakeIk()
    rows = []
    boundaries = []
    discarded = []
    episode = 0
    physics_step = 0
    tick = 0
    sequence = (
        (motion, motion),  # initial tracking rebase
        (motion, motion),
        (clutch, motion),
        (clutch, motion),
        (clutch, motion),
        (motion, motion),  # intentional clutch release rebase
        (motion, motion),
        (clutch, clutch),  # both hands intentional clutch
        (clutch, clutch),
        (motion, motion),
        (motion, motion),
        (lost, motion),
        (motion, motion),  # tracking recovery rebase
        (motion, motion),
    )
    for left, right in sequence:
        observation = physics_step
        command = processor.advance(left, right)
        eligible = recordable_teleop_command(command)
        if eligible:
            tick += 1
        else:
            discarded.append((command.left.transition, command.right.transition))
            if any(row["episode"] == episode for row in rows):
                boundaries.append((episode, command.left.transition))
                episode += 1
        decision = solve(ik, command, observation, object(), tick,
                         recording_requested=True, eligible=eligible)
        ik.apply(decision)
        physics_step += 4
        if eligible:
            rows.append({"episode": episode, "frame": sum(r["episode"] == episode for r in rows),
                         "ot": observation, "ot1": physics_step, "decision": decision,
                         "left": command.left.transition, "right": command.right.transition})

    first = [row for row in rows if row["episode"] == 0]
    assert [row["left"] for row in first[:6]] == [
        "motion", "clutch_engaged", "clutch_held", "clutch_held",
        "clutch_release_rebased", "motion",
    ]
    assert [row["frame"] for row in first] == list(range(len(first)))
    assert all(a["ot1"] == b["ot"] for a, b in zip(first, first[1:]))
    assert any(row["left"] == row["right"] == "clutch_held" for row in first)
    assert any(row["left"] == "clutch_held" and row["right"] == "motion" and
               np.any(row["decision"].native_target[6:]) for row in first)
    assert [reason for _, reason in boundaries] == ["tracking_lost"]
    assert [left for left, _ in discarded] == ["tracking_rebased", "tracking_lost", "tracking_rebased"]
    assert rows[-1]["episode"] == 1 and rows[-1]["frame"] == 0
    assert len(ik.applied) == len(sequence)


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
    assert recordable_teleop_command(command)
    ik = FakeIk()
    run = solve(ik, command, object(), object(), 7, recording_requested=False, eligible=True)
    record = solve(ik, command, object(), object(), 7, recording_requested=True, eligible=True)
    assert run[0] is record[0] is command
    assert run[1:] != (None, None, None) and record[1:] != (None, None, None)
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


def test_runtime_closes_static_session_once_after_episode_finalization():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text()
    assert source.count("recording_session = RecordingSession(") == 1
    assert source.count("recording_session.close(") == 1
    assert source.index("finalize_recording(recording_outcome, close_reason)") < source.index(
        "recording_session.close("
    )


@pytest.mark.parametrize("committed", [0, 1])
def test_interrupted_injected_audit_finalizes_without_claiming_pass(tmp_path, monkeypatch, committed):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "processor": {"revision": PROCESSOR_REVISION},
        "environment": {"isaac_lab_release": "pin", "cloudxr_runtime_version": "pin",
                        "materialized_path": "/data/runtime/env"},
        "asset": {"source_checkout": "/data/assets/source"},
    }))
    monkeypatch.setattr(isaac_vr_recording_smoke.importlib.metadata, "version", lambda name: "pin")
    monkeypatch.setitem(sys.modules, "isaacteleop.cloudxr.runtime", NS(runtime_version=lambda: "pin"))
    closes = []
    recording = NS(committed_frames=committed, discarded_observations=0,
                   episode_id="episode_000000", run_id="run", session_id="session",
                   output_dir=tmp_path, hdf5_path=tmp_path / "session.hdf5")

    class Session:
        def __init__(self, active, **kwargs):
            assert active is recording

        def close(self, *, outcome, reason):
            closes.append((outcome, reason))

    stopped = False

    def inject(active, env, *, stop_requested, input_pump, **kwargs):
        nonlocal stopped
        assert active is recording
        input_pump()
        stopped = True
        assert stop_requested()
        return {"committed_frames": committed, "accepted_transactions": committed,
                "stopped_by_user": True, "requested_control_steps": 3,
                "completed_control_budget": False, "input_pump_calls": 1}

    def validate(*args, **kwargs):
        raise AssertionError("An interrupted audit must not claim full reader qualification")

    monkeypatch.setitem(sys.modules, "isaac_vr_recording", NS(
        start_live_recording=lambda *args, **kwargs: recording, RecordingSession=Session))
    monkeypatch.setitem(sys.modules, "isaac_vr_injected_recording", NS(
        record_injected_transitions=inject, validate_injected_recording=validate))
    env = NS(vr_runtime=None)
    args = NS(config=config, s2_config=config, s2_record=True, s2_recording_dir=tmp_path,
              s2_teleop=True, xr=True, s2_injected_recording_smoke=True,
              s2_injected_count=3, s2_current_record_audit="steady", report=tmp_path / "result.json")
    device = NS(advance=lambda: None, session_running=False)
    code = isaac_vr_recording_smoke.run_recording_lifecycle_smoke(
        env, args, default_config_path=config, processor_revision=PROCESSOR_REVISION,
        audit_device=device, stop_requested=lambda: stopped,
    )
    result = json.loads(args.report.read_text())
    assert code == 130 and not result["passed"] and result["stopped_by_user"]
    assert result["committed_frames"] == committed and result["input_pump_calls"] == 1
    assert result["reason"] == "keyboard_interrupt"
    assert result["reader_validation"] == []
    assert closes == [("operator_stopped" if committed else "aborted", "keyboard_interrupt")]


@pytest.mark.parametrize("stop_at", ["gap_transition", "second_episode_input"])
def test_gap_audit_stop_keeps_completed_episode_and_actual_counts(tmp_path, monkeypatch, stop_at):
    from test_isaac_vr_injected_recording import FakeEnvironment, FakeRecording
    from isaac_s2_performance import S2PerformanceLogger
    import isaac_vr_episode_lifecycle as lifecycle

    env = FakeEnvironment()
    records, sealed = [], []
    stopped = False
    pumps = 0

    def new_recording(path, episode):
        recording = FakeRecording(env)
        recording.output_dir, recording.hdf5_path = path, path / "session.hdf5"
        recording.episode_id = episode
        recording.discarded_observations = 0
        recording.discard_observation = lambda *args, **kwargs: None
        records.append(recording)
        return recording

    original_advance = env._advance

    def advance(repeat):
        nonlocal stopped
        if env.pending is None:
            env.physics_step += repeat
            stopped = stop_at == "gap_transition"
        else:
            original_advance(repeat)

    def pump():
        nonlocal stopped, pumps
        pumps += 1
        if pumps == 4:
            stopped = True

    env._advance = advance
    session = NS(check_finalization=lambda: None,
                 end_episode=lambda **kwargs: sealed.append((records[-1], kwargs)),
                 start_episode=new_recording)
    monkeypatch.setattr(lifecycle, "technical_episode_output_dir", lambda **kwargs: tmp_path / "second")
    first = new_recording(tmp_path / "first", "episode_000000")
    args = NS(s2_audit_gaps=1, s2_recordings_root=tmp_path)
    logger = S2PerformanceLogger(tmp_path / "performance.jsonl", window_steps=2,
                                 warmup_steps=0, target_hz=30)
    try:
        last, result, paths = isaac_vr_recording_smoke._run_gap_audit(
            first, session, env, args, logger, NS(advance=pump), count=6,
            stop_requested=lambda: stopped,
        )
    finally:
        logger.close()
    expected_episodes = 1 if stop_at == "gap_transition" else 2
    assert result["stopped_by_user"] and not result["completed_control_budget"]
    assert result["accepted_transactions"] == result["committed_frames"] == 3
    assert result["input_pump_calls"] == pumps == (3 if expected_episodes == 1 else 4)
    assert len(result["technical_episodes"]) == len(paths) == expected_episodes
    assert sealed == [(first, {"outcome": "operator_stopped", "reason": "tracking_invalid"})]
    assert last is records[-1] and last.committed_frames == (3 if expected_episodes == 1 else 0)


@pytest.mark.parametrize("stop_at", ["input_pump", "transition"])
def test_lifecycle_audit_stop_seals_partial_demo_as_interrupted(tmp_path, monkeypatch, stop_at):
    from test_isaac_vr_injected_recording import FakeEnvironment, FakeRecording

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "processor": {"revision": PROCESSOR_REVISION},
        "environment": {"isaac_lab_release": "pin", "materialized_path": "/data/runtime/env"},
        "asset": {"source_checkout": "/data/assets/source"},
    }))
    monkeypatch.setattr(isaac_vr_recording_smoke.importlib.metadata, "version", lambda name: "pin")
    monkeypatch.setitem(sys.modules, "isaacteleop.cloudxr.runtime", NS(runtime_version=lambda: "pin"))
    env = FakeEnvironment()
    env.vr_runtime.disable_live_rgb = lambda: None
    env.vr_runtime.close = lambda: None
    active = FakeRecording(env)
    active.output_dir, active.hdf5_path = tmp_path, tmp_path / "session.hdf5"
    closes = []

    class Session:
        def __init__(self, recording):
            assert recording is active

        def close(self, **kwargs):
            closes.append(kwargs)

    monkeypatch.setitem(sys.modules, "isaac_vr_recording", NS(
        start_live_recording=lambda *args, **kwargs: active, RecordingSession=Session,
        # The real injected function still builds and verifies causal rows.
        build_committed_transition_sample=__import__("tools.isaac_vr_recording", fromlist=[
            "build_committed_transition_sample"]).build_committed_transition_sample))
    stopped = False
    original_advance = env._advance

    def advance(repeat):
        nonlocal stopped
        original_advance(repeat)
        stopped = True

    def pump():
        nonlocal stopped
        if stop_at == "input_pump":
            stopped = True

    if stop_at == "transition":
        env._advance = advance
    args = NS(config=config, s2_config=config, s2_recordings_root=tmp_path,
              s2_recording_dir=tmp_path, s2_injected_count=3, s2_audit_lifecycle_cycles=2,
              s2_performance_log=tmp_path / "performance.jsonl", s2_performance_window_steps=2,
              s2_performance_warmup_steps=0, xr=True, s2_cloudxr_profile="cloudxrjs",
              report=tmp_path / "report.json")
    device = NS(advance=pump, session_running=False, reset=lambda **kwargs: None)
    code = isaac_vr_recording_smoke.run_injected_lifecycle_audit(
        env, args, default_config_path=config, processor_revision=PROCESSOR_REVISION,
        audit_device=device, stop_requested=lambda: stopped,
    )
    result = json.loads(args.report.read_text())
    committed = int(stop_at == "transition")
    assert code == 130 and not result["passed"] and result["stopped_by_user"]
    assert result["cycles"] == 0 and result["requested_cycles"] == 2
    assert result["control_steps"] == committed and result["input_pump_calls"] == 1
    assert result["requested_control_steps"] == 6 and not result["completed_control_budget"]
    assert result["events"] == result["reader_validation"] == []
    assert result["technical_episodes"][0]["committed_frames"] == committed
    assert closes == [{"outcome": "operator_stopped" if committed else "aborted",
                       "reason": "keyboard_interrupt"}]
    indexes = list((tmp_path / "interrupted_demos").glob("*.json"))
    assert len(indexes) == 1 and json.loads(indexes[0].read_text())["classification"] == "interrupted"
    assert not (tmp_path / "saved_demos").exists()


@pytest.mark.parametrize("stop_at", ["input_pump", "transition"])
def test_no_client_run_route_returns_interrupted_report(tmp_path, monkeypatch, stop_at):
    from test_isaac_vr_injected_recording import FakeEnvironment
    from isaac_s2_performance import S2PerformanceLogger
    import isaac_vr_injected_recording as injected

    # Execute the runtime's actual early audit branch; vendor construction and
    # version preflight happen before this branch and are outside this stop seam.
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text()
    run = next(node for node in ast.parse(source).body
               if isinstance(node, ast.FunctionDef) and node.name == "run_s2")
    audit = next(node for node in run.body if isinstance(node, ast.If)
                 and "s2_current_record_audit" in ast.unparse(node.test))
    wrapper = ast.parse("def route(env, args_cli, device, stop_requested): pass").body[0]
    wrapper.body = [audit]
    namespace = {"experiment": None, "recording_requested": False,
                 "S2PerformanceLogger": S2PerformanceLogger, "Path": Path, "json": json}
    exec(compile(ast.fix_missing_locations(ast.Module([wrapper], [])), "audit_route", "exec"),
         namespace)
    env = FakeEnvironment()
    monkeypatch.setattr(injected, "capture_state_snapshot", lambda env: None)
    stopped = False
    original_advance = env._advance
    device_closed = []

    def advance(repeat):
        nonlocal stopped
        original_advance(repeat)
        stopped = True

    class Device:
        session_running = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            device_closed.append(True)

        def advance(self):
            nonlocal stopped
            if stop_at == "input_pump":
                stopped = True

    if stop_at == "transition":
        env._advance = advance
    args = NS(s2_current_record_audit="steady", s2_injected_count=3,
              s2_performance_log=tmp_path / "performance.jsonl", s2_performance_window_steps=2,
              s2_performance_warmup_steps=0, xr=True, s2_cloudxr_profile="cloudxrjs",
              report=tmp_path / "report.json")
    assert namespace["route"](env, args, Device(), lambda: stopped) == 130
    assert device_closed == [True]
    result = json.loads(args.report.read_text())
    assert not result["passed"] and result["stopped_by_user"]
    assert result["control_steps"] == int(stop_at == "transition")
    assert result["requested_control_steps"] == 3 and not result["completed_control_budget"]
    assert result["input_pump_calls"] == 1
