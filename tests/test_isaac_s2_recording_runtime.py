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
    assert '"source_profile": "isaac_human_vr_offline_rgb_v1"' in metadata_source
    assert 'episode_id = "episode_000000"' in source
    assert "recording.episode_id if recording is not None" in source
    assert "recording.sample(" not in source
    assert 'outcome="unclassified"' not in source


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
    assert 'recording_episode_index += 1' in source
    assert '"recording_episodes"' in source
    assert '"left_transition": command.left.transition' in source


def test_rejected_recording_tick_does_not_rearm_processor_or_apply_native_command():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    solution = source.index("solution = _solve_native_decision(")
    gated_apply = source.index("if solution is not None:", solution)
    native_apply = source.index("saturated_frames += int(ik.apply(solution))", gated_apply)
    assert solution < gated_apply < native_apply

    node = next(
        node for node in ast.parse(source).body
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
            return object()

    ik = FakeIk()
    processor = BimanualS2TeleopProcessor()
    tracked = ControllerDeltaSample(
        np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0
    )
    clutched = ControllerDeltaSample(
        np.ones(3), np.ones(3), True, True, 1.0, 0.0, 0.0
    )
    untracked = ControllerDeltaSample(
        np.ones(3), np.ones(3), False, False, 0.0, 0.0, 0.0
    )
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
    for left, right in sequence:
        command = processor.advance(left, right)
        generation = processor.generation
        eligible = recordable_teleop_command(command)
        decisions.append(solve(
            ik, command, object(), object(), len(decisions) + 1,
            recording_requested=True, eligible=eligible,
        ))
        assert processor.generation == generation
    assert [decision is not None for decision in decisions] == [
        False, True, False, False, False, True, False, False, True
    ]
    assert len(ik.calls) == 3


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
