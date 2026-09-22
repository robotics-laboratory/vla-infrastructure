"""Fail-closed replay artifact and pre-scene ordering tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from tools import isaac_vr_replay as replay
from tools.isaac_vr_asset_closure import build_asset_closure_manifest
from test_isaac_vr_recording import committed_sample, seal_sample


def _artifact(tmp_path: Path, **updates) -> Path:
    recording = tmp_path / "session.hdf5"
    snapshot = tmp_path / "stage_snapshot.usd"
    recording.write_bytes(b"hdf-v2")
    snapshot.write_bytes(b"#usda 1.0")
    portable_roots = {"recording": tmp_path}
    asset_closure = build_asset_closure_manifest(
        snapshot,
        portable_roots=portable_roots,
        dependency_provider=lambda _snapshot: ((), (), ()),
    )
    (tmp_path / "asset_closure.json").write_text(json.dumps(asset_closure))
    manifest = {
        "schema": "piper_x_isaac_vr_recording_manifest_v2",
        "artifact_state": "finalized",
        "asset_closure": "asset_closure.json",
        "asset_closure_sha256": asset_closure["asset_closure_sha256"],
        "hdf5": recording.name,
        "hdf5_sha256": hashlib.sha256(recording.read_bytes()).hexdigest(),
        "stage_snapshot": snapshot.name,
        "stage_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "camera_roles": {
            "left_wrist": "/World/Left/Camera",
            "right_wrist": "/World/Right/Camera",
            "scene": "/World/SceneCamera",
        },
        "committed_frames": 2,
        "outcome": "operator_stopped",
        "pose_backend_effective": "fabric",
        "pose_backend_requested": "fabric",
        "transition_schema": "piper_x_committed_transition_v2",
        "session_metadata": {
            "run_id": "run",
            "session_id": "session",
            "episode_id": "episode_000000",
            "source_profile": "isaac_human_vr_offline_rgb_v1",
        },
    }
    manifest.update(updates)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "recording_state.json").write_text(
        json.dumps(
            {
                "artifact_state": manifest["artifact_state"],
                "committed_frames": manifest["committed_frames"],
                "hdf5_sha256": manifest["hdf5_sha256"],
                "outcome": manifest["outcome"],
            }
        )
    )
    return recording


def _verify(recording: Path):
    return replay.verify_recording_artifact(
        recording,
        portable_roots={"recording": recording.parent},
    )


def _canonical_d0_arrays() -> dict[str, np.ndarray]:
    first = committed_sample()
    first["episode_id"] = "episode_000000"
    seal_sample(first)
    second = committed_sample(frame_index=1, successor_step=18)
    second.update(
        {
            "episode_id": "episode_000000",
            "obs_id": first["next_obs_id"],
            "scene_state_snapshot_id": first["next_scene_state_snapshot_id"],
            "scene_state_snapshot_sha256": first["next_scene_state_snapshot_sha256"],
            "observation_state": first["successor_observation_state"].copy(),
            "observation_physics_step": first["successor_physics_step"],
            "observation_capture_sequence": first["successor_capture_sequence"],
            "simulation_state_generation": first["successor_state_generation"],
            "dataset_action_id": "action:1",
            "action_source_id": "xr.resolved_input:1",
            "dataset_action": np.arange(14, dtype=np.float32) + 2000,
            "processor_generation": 6,
            "native_command_id": "native:1",
            "transition_id": "transition:1",
            "next_obs_id": "obs:2",
            "next_scene_state_snapshot_id": "snapshot:2",
            "successor_observation_state": np.arange(14, dtype=np.float32) + 2,
            "successor_capture_sequence": 2,
            "control_tick_id": 1,
            "deviceio_update_epoch": 4,
            "submitted_frame_id": 5,
            "returned_frame_id": 5,
            "xr_deviceio_source_id": "xr.device_io_update:1",
            "xr_submitted_source_id": "xr.submitted_frame:1",
            "xr_returned_source_id": "xr.returned_frame:1",
            "xr_resolved_source_id": "xr.resolved_input:1",
        }
    )
    seal_sample(second)
    return {
        name: np.stack((np.asarray(first[name]), np.asarray(second[name])))
        for name in first
    }


def test_artifact_verifier_accepts_only_finalized_v2_and_streaming_hashes(tmp_path):
    recording = _artifact(tmp_path)
    artifact = _verify(recording)
    assert artifact.recording == recording
    assert artifact.snapshot == tmp_path / "stage_snapshot.usd"
    assert tuple(artifact.camera_paths) == replay.CANONICAL_CAMERA_ROLES

    recording.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="HDF5 digest mismatch"):
        _verify(recording)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"schema": "piper_x_isaac_vr_recording_manifest_v1"}, "unsupported"),
        ({"artifact_state": "in_progress"}, "not finalized"),
        ({"stage_snapshot": "../escape.usd"}, "safe artifact-relative"),
        (
            {
                "camera_roles": {
                    "left_wrist": "/Same",
                    "right_wrist": "/Same",
                    "scene": "/Scene",
                }
            },
            "must be unique",
        ),
    ],
)
def test_artifact_verifier_rejects_untrusted_metadata(tmp_path, updates, message):
    recording = _artifact(tmp_path, **updates)
    with pytest.raises(ValueError, match=message):
        _verify(recording)


def test_artifact_verifier_rejects_snapshot_mutation(tmp_path):
    recording = _artifact(tmp_path)
    (tmp_path / "stage_snapshot.usd").write_bytes(b"changed")
    with pytest.raises(ValueError, match="snapshot digest mismatch"):
        _verify(recording)


def test_artifact_verifier_requires_sidecar_digest_and_explicit_root_binding(tmp_path):
    recording = _artifact(tmp_path)
    (tmp_path / "asset_closure.json").unlink()
    with pytest.raises(FileNotFoundError, match="asset closure not found"):
        _verify(recording)

    recording = _artifact(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["asset_closure_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="aggregate hashes differ"):
        _verify(recording)

    recording = _artifact(tmp_path)
    with pytest.raises(ValueError, match="root bindings|required"):
        replay.verify_recording_artifact(recording, portable_roots={})


def test_session_validator_requires_every_row_committed_and_every_track(tmp_path):
    artifact = _verify(_artifact(tmp_path))
    tracks = [
        {"group": group, "type": replay.REQUIRED_TRACK_TYPES[group]}
        for group in replay.REQUIRED_TRACKS
    ]

    class Reader:
        def list_episodes(self):
            return ["episode_000000"]

        def normalize_episode(self, episode):
            assert episode == 0
            return "episode_000000"

        def num_frames(self, episode):
            return 2

        def manifest(self):
            return SimpleNamespace(
                tracks=tracks,
                session={
                    **artifact.manifest["session_metadata"],
                    "stage_snapshot": artifact.snapshot.name,
                    "stage_snapshot_sha256": artifact.snapshot_sha256,
                    "asset_closure_sha256": artifact.asset_closure_sha256,
                },
                sampling={
                    "mode": "explicit_committed_control_boundary",
                    "pose_backend": "fabric",
                },
            )

        def episode_attrs(self, episode):
            return {"num_frames": 2, "success": False}

        def read_group_all_frames(self, episode, group):
            return _canonical_d0_arrays()

    session = replay._validate_session(Reader(), artifact, 0)
    assert session.frames == session.committed_count == 2

    broken = Reader()
    broken_rows = _canonical_d0_arrays()
    broken_rows["committed"][1] = 0
    broken.read_group_all_frames = lambda *args: broken_rows
    with pytest.raises(RuntimeError, match="causally committed"):
        replay._validate_session(broken, artifact, 0)

    broken_rows = _canonical_d0_arrays()
    broken_rows["next_obs_id"][0] = "obs-x"
    broken.read_group_all_frames = lambda *args: broken_rows
    with pytest.raises(RuntimeError, match="successor continuity mismatch"):
        replay._validate_session(broken, artifact, 0)

    broken_rows = _canonical_d0_arrays()
    broken_rows["observation_payload_sha256"][0] = "0" * 64
    broken.read_group_all_frames = lambda *args: broken_rows
    with pytest.raises(RuntimeError, match="does not verify"):
        replay._validate_session(broken, artifact, 0)


def test_frame_guard_checks_quiescence_after_every_pump_and_materialization():
    events = []

    class Replayer:
        def apply_frame(self, frame):
            events.append(("apply", frame))

    replay.apply_replay_frames(
        Replayer(),
        2,
        pump=lambda: events.append(("pump", None)),
        materialize=lambda frame: events.append(("render", frame)),
        assert_quiescent=lambda: events.append(("guard", None)),
        physics_steps=lambda: 7,
    )
    assert events == [
        ("apply", 0), ("pump", None), ("render", 0), ("guard", None),
        ("apply", 1), ("pump", None), ("render", 1), ("guard", None),
    ]


def test_pre_scene_entry_opens_snapshot_before_strict_prepare(tmp_path, monkeypatch):
    artifact = _verify(_artifact(tmp_path))
    events = []

    class Reader:
        def __init__(self, path):
            events.append("reader")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Policy:
        def __init__(self, *, strictness):
            assert strictness == "strict"
            self.strictness = strictness

    class Replayer:
        def __init__(self, path, *, policy, pose_backend):
            assert policy.strictness == "strict" and pose_backend == "usd"
            events.append("replayer")

        def prepare_episode(self, episode):
            assert "open" in events
            events.append("prepare")

        def prepared_recordables(self):
            return [SimpleNamespace(group=group) for group in replay.REQUIRED_TRACKS]

        def apply_frame(self, frame):
            events.append("apply")

        def close(self):
            events.append("close")

    extension = ModuleType("isaacsim.replicator.episode_recorder")
    extension.EpisodeReplayer = Replayer
    extension.ReplayPolicy = Policy
    extension.SessionReader = Reader
    monkeypatch.setitem(sys.modules, "isaacsim.replicator.episode_recorder", extension)
    recording_module = ModuleType("isaac_vr_recording")
    recording_module.ensure_d0_recordable = lambda: events.append("register")
    monkeypatch.setitem(sys.modules, "isaac_vr_recording", recording_module)
    monkeypatch.setattr(
        replay,
        "verify_recording_artifact",
        lambda path, *, portable_roots: artifact,
    )
    monkeypatch.setattr(
        replay,
        "_validate_session",
        lambda *args: replay.ReplaySession(
            "episode_000000", 1, tuple({"group": group} for group in replay.REQUIRED_TRACKS),
            ("obs-0",), 1,
        ),
    )
    monkeypatch.setattr(replay, "_open_verified_snapshot", lambda *args: events.append("open"))

    class Guard:
        physics_callbacks = []

        def configure(self): events.append("guard_configure")
        def start_monitoring(self): events.append("monitor")
        def assert_quiescent(self): events.append("quiet")
        def close(self): events.append("guard_close")

    monkeypatch.setattr(replay, "ReplayRuntimeGuard", Guard)
    app = SimpleNamespace(update=lambda: events.append("pump"))
    report = tmp_path / "report.json"
    assert replay.replay_from_snapshot(
        app,
        recording=artifact.recording,
        episode=0,
        render_cameras=None,
        report_path=report,
        portable_roots={"recording": tmp_path},
    ) == 0
    assert events.index("open") < events.index("replayer") < events.index("prepare")
    payload = json.loads(report.read_text())
    assert payload["strict_policy"] is True
    assert payload["physics_callbacks"] == 0
