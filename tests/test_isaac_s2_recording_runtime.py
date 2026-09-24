"""Seam checks for the Kit-owned S2 recording transaction order."""

import ast
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import yaml
import numpy as np

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
    assert "if event not in (\"stop\", \"save\", \"discard\")" in source
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
    assert source.count("recording_session = RecordingSession(recording)") == 1
    assert source.count("recording_session.close(") == 1
    assert source.index("finalize_recording(recording_outcome, close_reason)") < source.index(
        "recording_session.close("
    )
