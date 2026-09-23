"""Seam checks for the Kit-owned S2 recording transaction order."""

import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import yaml

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


def test_recording_gap_stops_before_unrecorded_native_advance():
    source = (ROOT / "tools/isaac_s2_runtime.py").read_text(encoding="utf-8")
    discard = source.index(
        "recording.discard_observation(", source.index("if recording is not None and not eligible:")
    )
    continuity_guard = source.index("if recording.committed_frames:", discard)
    stop = source.index("break", continuity_guard)
    native_apply = source.index("saturated_frames += int(ik.apply(solution))", stop)
    assert discard < continuity_guard < stop < native_apply


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
