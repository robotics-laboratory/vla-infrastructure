"""Pure-Python contract tests for the committed NVIDIA V2 coordinator."""

from contextlib import nullcontext
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools.isaac_vr_recording import (
    ExplicitFrameSampler,
    LiveRecording,
    _d0_channels,
    _empty_d0_sample,
    build_committed_transition_sample,
    canonical_transition_outcome_payload,
    canonical_committed_transition,
    close_explicit_session,
    enrich_recording_session_metadata,
    prepare_private_output_dir,
    sha256_file,
    verify_committed_transition_sample,
    write_asset_closure_sidecar,
)
from tools.isaac_vr_decision import (
    StateSnapshotObservation,
    canonical_action_payload,
    canonical_hands_sha256,
    canonical_native_command_payload,
    canonical_state_snapshot_payload,
    canonical_xr_payload_from_fields,
)
from tools.isaac_vr_replay import apply_replay_frames


class FakeStorage:
    def __init__(self):
        self.frames, self.advanced = [], 0

    def append_frame(self, group, frame):
        self.frames.append((group, dict(frame)))

    def advance_episode_frame(self):
        self.advanced += 1


class FakeRecordable:
    def __init__(self, group, marker, *, broken=False):
        self.group, self.marker, self.broken = group, marker, broken

    def describe_channels(self):
        return {"marker": SimpleNamespace(shape=(), dtype="i8")}

    def sample(self):
        if self.broken:
            raise RuntimeError("sample failed")
        return {"marker": np.int64(self.marker)}


def test_explicit_frame_is_atomic_at_advance_boundary():
    storage = FakeStorage()
    sampler = ExplicitFrameSampler(
        storage,
        (FakeRecordable("world", 0), FakeRecordable("d0/transition", 1000)),
        backend_context_factory=nullcontext,
    )
    sampler.sample_frame()
    assert storage.advanced == 1
    assert storage.frames == [("world", {"marker": np.int64(0)}), ("d0/transition", {"marker": np.int64(1000)})]


def test_failed_recordable_never_advances_and_fails_closed():
    storage = FakeStorage()
    sampler = ExplicitFrameSampler(
        storage,
        (FakeRecordable("world", 0), FakeRecordable("d0", 1, broken=True)),
        backend_context_factory=nullcontext,
    )
    with pytest.raises(RuntimeError, match="sample failed"):
        sampler.sample_frame()
    assert storage.advanced == 0
    with pytest.raises(RuntimeError, match="failed closed"):
        sampler.sample_frame()


def test_d0_schema_has_explicit_ot_action_successor_and_outcome_channels():
    class Descriptor:
        def __init__(self, *, shape, dtype, **_):
            self.shape, self.dtype = shape, dtype

    channels = _d0_channels(Descriptor)
    sample = _empty_d0_sample()
    assert channels["observation_state"].shape == channels["dataset_action"].shape == (14,)
    assert channels["successor_observation_state"].shape == (14,)
    assert sample["frame_index"] == -1 and sample["committed"] == 0
    assert {"obs_id", "dataset_action_id", "native_command_id", "transition_id", "next_obs_id"} <= set(channels)
    assert {"transition_outcome", "terminated", "success", "failure_code", "failure_reason"} <= set(channels)
    for name, value in sample.items():
        assert np.asarray(value).shape == channels[name].shape
        assert np.asarray(value).dtype.kind in "biufS"


def committed_sample(*, frame_index=0, committed=1, successor_step=14, outcome="continued"):
    digest = hashlib.sha256(b"fixture").hexdigest()
    sample = {
        "schema_version": 2,
        "frame_index": frame_index,
        "run_id": "run",
        "session_id": "session",
        "episode_id": "episode",
        "source_id": "simulation.scene_state_snapshot",
        "source_epoch": "7",
        "obs_id": "obs:0",
        "scene_state_snapshot_id": "snapshot:0",
        "scene_state_snapshot_sha256": digest,
        "observation_payload_sha256": digest,
        "observation_state": np.arange(14, dtype=np.float32),
        "observation_physics_step": 10,
        "observation_capture_sequence": 0,
        "simulation_state_generation": 10,
        "dataset_action_id": "action:0",
        "action_source_id": "xr.resolved_input:0",
        "action_payload_sha256": digest,
        "action_source_sha256": digest,
        "dataset_action": np.arange(14, dtype=np.float32) + 1000,
        "processor_revision": "processor-v1",
        "processor_provenance_revision": "provenance-v1",
        "processor_generation": 5,
        "native_command_id": "native:0",
        "native_command_sha256": digest,
        "native_preclip": np.arange(14, dtype=np.float32) / 10,
        "native_clipped": np.arange(14, dtype=np.float32) / 10,
        "native_residual": np.zeros(14, dtype=np.float32),
        "saturation": np.zeros(14, dtype=np.uint8),
        "transition_id": "transition:0",
        "transition_payload_sha256": digest,
        "transition_outcome": outcome,
        "terminated": int(outcome != "continued"),
        "success": int(outcome == "terminated_success"),
        "failure_code": "task_failure" if outcome == "terminated_failure" else "",
        "failure_reason": "fixture" if outcome == "terminated_failure" else "",
        "next_obs_id": "obs:1",
        "next_scene_state_snapshot_id": "snapshot:1",
        "next_scene_state_snapshot_sha256": digest,
        "successor_payload_sha256": digest,
        "successor_observation_state": np.arange(14, dtype=np.float32) + 1,
        "successor_physics_step": successor_step,
        "successor_capture_sequence": 1,
        "successor_state_generation": successor_step,
        "successor_reset_epoch": 0,
        "control_tick_id": 0,
        "reset_epoch": 0,
        "control_reference_epoch": 2,
        "session_epoch": 7,
        "deviceio_update_epoch": 3,
        "submitted_frame_id": 4,
        "returned_frame_id": 4,
        "xr_deviceio_source_id": "xr.device_io_update:0",
        "xr_deviceio_source_sha256": digest,
        "xr_submitted_source_id": "xr.submitted_frame:0",
        "xr_submitted_source_sha256": digest,
        "xr_returned_source_id": "xr.returned_frame:0",
        "xr_returned_source_sha256": digest,
        "xr_resolved_source_id": "xr.resolved_input:0",
        "xr_resolved_source_sha256": digest,
        "xr_ran_synchronously": 1,
        "xr_rebased": 0,
        "tracking_valid": np.ones(2, dtype=np.uint8),
        "xr_world_transform": np.eye(4, dtype=np.float32).reshape(-1),
        "xr_hands_sha256": digest,
        "committed": committed,
    }
    return sample


def seal_sample(row):
    row["observation_payload_sha256"] = hashlib.sha256(
        canonical_state_snapshot_payload(
            reset_epoch=row["reset_epoch"],
            physics_step=row["observation_physics_step"],
            state_generation=row["simulation_state_generation"],
            capture_sequence=row["observation_capture_sequence"],
            scene_state_snapshot_id=row["scene_state_snapshot_id"],
            scene_state_snapshot_sha256=row["scene_state_snapshot_sha256"],
            state=row["observation_state"],
        )
    ).hexdigest()
    row["successor_payload_sha256"] = hashlib.sha256(
        canonical_state_snapshot_payload(
            reset_epoch=row["successor_reset_epoch"],
            physics_step=row["successor_physics_step"],
            state_generation=row["successor_state_generation"],
            capture_sequence=row["successor_capture_sequence"],
            scene_state_snapshot_id=row["next_scene_state_snapshot_id"],
            scene_state_snapshot_sha256=row["next_scene_state_snapshot_sha256"],
            state=row["successor_observation_state"],
        )
    ).hexdigest()
    row["action_payload_sha256"] = hashlib.sha256(
        canonical_action_payload(
            row["dataset_action"],
            processor_revision=row["processor_revision"],
            provenance_revision=row["processor_provenance_revision"],
            processor_generation=row["processor_generation"],
        )
    ).hexdigest()
    row["native_command_sha256"] = hashlib.sha256(
        canonical_native_command_payload(
            preclip=row["native_preclip"],
            clipped=row["native_clipped"],
            residual=row["native_residual"],
            saturation=row["saturation"],
        )
    ).hexdigest()
    row["transition_payload_sha256"] = hashlib.sha256(
        canonical_transition_outcome_payload(
            transition_id=row["transition_id"],
            transition_outcome=row["transition_outcome"],
            terminated=bool(row["terminated"]),
            success=bool(row["success"]),
            failure_code=row["failure_code"],
            failure_reason=row["failure_reason"],
        )
    ).hexdigest()
    xr_sha = hashlib.sha256(
        canonical_xr_payload_from_fields(
            session_epoch=row["session_epoch"],
            control_reference_epoch=row["control_reference_epoch"],
            deviceio_update_epoch=row["deviceio_update_epoch"],
            submitted_frame_id=row["submitted_frame_id"],
            returned_frame_id=row["returned_frame_id"],
            ran_synchronously=bool(row["xr_ran_synchronously"]),
            rebased=bool(row["xr_rebased"]),
            tracking_valid=row["tracking_valid"],
            world_transform=row["xr_world_transform"],
            hands_sha256=row["xr_hands_sha256"],
        )
    ).hexdigest()
    for field in (
        "action_source_sha256",
        "xr_deviceio_source_sha256",
        "xr_submitted_source_sha256",
        "xr_returned_source_sha256",
        "xr_resolved_source_sha256",
    ):
        row[field] = xr_sha
    return row


def test_committed_schema_preserves_distinguishable_ot_at_and_successor():
    result = canonical_committed_transition(committed_sample())
    assert result["frame_index"] == 0
    np.testing.assert_array_equal(result["observation_state"], np.arange(14))
    np.testing.assert_array_equal(result["dataset_action"], np.arange(14) + 1000)
    np.testing.assert_array_equal(result["successor_observation_state"], np.arange(14) + 1)


def test_row_payload_hashes_recompute_and_mutation_fails_closed():
    row = canonical_committed_transition(seal_sample(committed_sample()))
    verify_committed_transition_sample(row)
    row["dataset_action"] = row["dataset_action"].copy()
    row["dataset_action"][3] += np.float32(0.25)
    with pytest.raises(ValueError, match="action_payload_sha256"):
        verify_committed_transition_sample(row)


@pytest.mark.parametrize(
    ("mutation", "digest_field"),
    [
        (lambda row: row["observation_state"].__setitem__(0, 9.0), "observation_payload_sha256"),
        (lambda row: row["successor_observation_state"].__setitem__(0, 9.0), "successor_payload_sha256"),
        (lambda row: row.update(processor_generation=6), "action_payload_sha256"),
        (
            lambda row: (
                row["native_preclip"].__setitem__(0, row["native_preclip"][0] + 0.25),
                row["native_clipped"].__setitem__(0, row["native_clipped"][0] + 0.25),
            ),
            "native_command_sha256",
        ),
        (lambda row: row["xr_world_transform"].__setitem__(0, 2.0), "action_source_sha256"),
        (lambda row: row.update(failure_reason="changed"), "transition_payload_sha256"),
    ],
)
def test_each_canonical_payload_digest_detects_row_mutation(mutation, digest_field):
    row = canonical_committed_transition(seal_sample(committed_sample()))
    mutated = copy.deepcopy(row)
    mutation(mutated)
    with pytest.raises(ValueError, match=digest_field):
        verify_committed_transition_sample(mutated)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda row: row.update(committed=0), "causally committed"),
        (lambda row: row.update(next_obs_id=row["obs_id"]), "must differ"),
        (lambda row: row.update(successor_physics_step=10), "four steps after"),
        (lambda row: row.update(successor_capture_sequence=2), "exactly one"),
        (lambda row: row.update(successor_reset_epoch=1), "reset epoch"),
        (lambda row: row.update(transition_outcome="terminated_success"), "termination/success"),
        (lambda row: row.update(success=1), "non-terminated"),
        (lambda row: row.update(tracking_valid=np.array([1, 0], dtype=np.uint8)), "tracking"),
        (lambda row: row.update(saturation=np.array([1] + [0] * 13, dtype=np.uint8)), "saturation"),
        (lambda row: row.update(native_residual=np.ones(14, dtype=np.float32)), "native_residual"),
        (lambda row: row.update(observation_state=np.full(14, np.nan)), "non-finite"),
    ],
)
def test_committed_schema_rejects_false_admission_and_pairing(mutate, match):
    row = committed_sample()
    mutate(row)
    with pytest.raises(ValueError, match=match):
        canonical_committed_transition(row)


def test_deferred_group_is_never_sampled_and_only_complete_frame_advances():
    storage = FakeStorage()
    deferred = FakeRecordable("d0/committed_transition", 999, broken=True)
    sampler = ExplicitFrameSampler(
        storage,
        (FakeRecordable("world", 7), deferred),
        deferred_groups=(deferred.group,),
        backend_context_factory=nullcontext,
    )
    captured = sampler.capture_frame()
    assert captured == {"world": {"marker": np.int64(7)}}
    with pytest.raises(ValueError, match="captured groups"):
        sampler.append_captured_frame(captured)
    assert storage.advanced == 0 and storage.frames == []
    sampler.append_captured_frame({**captured, deferred.group: {"marker": np.int64(1007)}})
    assert storage.advanced == 1


def test_fabric_context_failure_fails_closed_before_sampling():
    def unavailable():
        raise RuntimeError("FSD disabled")

    sampler = ExplicitFrameSampler(FakeStorage(), (FakeRecordable("world", 1),), backend_context_factory=unavailable)
    with pytest.raises(RuntimeError, match="FSD disabled"):
        sampler.capture_frame()
    with pytest.raises(RuntimeError, match="failed closed"):
        sampler.capture_frame()


def test_pose_participants_use_one_shared_batch_and_never_fallback_to_sample():
    class PoseRecordable(FakeRecordable):
        def pose_paths(self):
            return [f"/World/{self.group}/a", f"/World/{self.group}/b"]

        def describe_channels(self):
            return {
                "positions": SimpleNamespace(shape=(2, 3), dtype="f4"),
                "orientations": SimpleNamespace(shape=(2, 4), dtype="f4"),
            }

        def sample(self):
            raise AssertionError("pose participant must not use per-recordable sample")

        def consume_pose_batch(self, positions, orientations):
            return {"positions": positions, "orientations": orientations}

    class Batch:
        def __init__(self):
            self.calls = 0

        def get_world_poses(self):
            self.calls += 1
            return np.arange(12, dtype=np.float32).reshape(4, 3), np.arange(
                16, dtype=np.float32
            ).reshape(4, 4)

    paths, batch = [], Batch()

    def factory(selected):
        paths.extend(selected)
        return batch

    sampler = ExplicitFrameSampler(
        FakeStorage(),
        (PoseRecordable("robot", 0), PoseRecordable("objects", 0)),
        backend_context_factory=nullcontext,
        pose_batch_factory=factory,
    )
    captured = sampler.capture_frame()
    assert paths == [
        "/World/robot/a", "/World/robot/b", "/World/objects/a", "/World/objects/b"
    ]
    assert batch.calls == 1
    np.testing.assert_array_equal(captured["robot"]["positions"], np.arange(6).reshape(2, 3))
    np.testing.assert_array_equal(
        captured["objects"]["positions"], np.arange(6, 12).reshape(2, 3)
    )


def test_shared_pose_batch_read_failure_is_terminal():
    class PoseRecordable(FakeRecordable):
        def pose_paths(self):
            return ["/World/robot"]

        def consume_pose_batch(self, positions, orientations):
            raise AssertionError("unreachable")

    class BrokenBatch:
        def get_world_poses(self):
            raise RuntimeError("fabric batch failed")

    sampler = ExplicitFrameSampler(
        FakeStorage(),
        (PoseRecordable("robot", 0),),
        backend_context_factory=nullcontext,
        pose_batch_factory=lambda _: BrokenBatch(),
    )
    with pytest.raises(RuntimeError, match="fabric batch failed"):
        sampler.capture_frame()
    with pytest.raises(RuntimeError, match="failed closed"):
        sampler.capture_frame()


class FakeLifecycleStorage(FakeStorage):
    def __init__(self):
        super().__init__()
        self.flushed = 0
        self.ended = []
        self.closed = False

    def flush(self):
        self.flushed += 1

    def end_episode(self, *, success, metadata):
        self.ended.append((success, metadata))

    def close(self):
        self.closed = True


class FakeLifecycleRecordable(FakeRecordable):
    def on_episode_end(self):
        pass

    def on_session_close(self):
        pass


def test_close_lifecycle_attempts_every_cleanup_after_callback_failure():
    events = []

    class Storage:
        def end_episode(self, **kwargs):
            events.append("end_episode")

        def close(self):
            events.append("storage_close")

    class Recordable:
        def __init__(self, name, *, fail=False):
            self.name, self.fail = name, fail

        def on_episode_end(self):
            events.append(f"episode:{self.name}")
            if self.fail:
                raise RuntimeError(f"broken:{self.name}")

        def on_session_close(self):
            events.append(f"session:{self.name}")

    with pytest.raises(RuntimeError, match="broken:first"):
        close_explicit_session(
            Storage(),
            (Recordable("first", fail=True), Recordable("second")),
            success=False,
            metadata={},
        )
    assert events == [
        "episode:first",
        "episode:second",
        "end_episode",
        "session:second",
        "session:first",
        "storage_close",
    ]


class FakeD0Recordable(FakeLifecycleRecordable):
    def describe_channels(self):
        class Descriptor:
            def __init__(self, *, shape, dtype, **_):
                self.shape, self.dtype = shape, dtype

        return _d0_channels(Descriptor)


class Observation:
    reset_epoch = 0
    physics_step = 10
    state_generation = 10
    state = tuple(float(value) + 0.1 for value in range(14))


def make_live(tmp_path: Path):
    storage = FakeLifecycleStorage()
    world = FakeLifecycleRecordable("world", 7)
    d0 = FakeD0Recordable("d0/committed_transition", 0)
    sampler = ExplicitFrameSampler(
        storage,
        (world, d0),
        deferred_groups=(d0.group,),
        backend_context_factory=nullcontext,
    )
    snapshot = tmp_path / "stage_snapshot.usd"
    hdf = tmp_path / "session.hdf5"
    snapshot.write_bytes(b"usd")
    hdf.write_bytes(b"hdf")
    (tmp_path / "manifest.json").write_text(json.dumps({"artifact_state": "in_progress"}))
    capture_count = 0

    def observation_factory():
        nonlocal capture_count
        observation = StateSnapshotObservation(
            reset_epoch=0,
            physics_step=10 + capture_count * 4,
            state_generation=10 + capture_count * 4,
            state=tuple(float(value + capture_count) + 0.1 for value in range(14)),
        )
        capture_count += 1
        return observation

    live = LiveRecording(
        storage,
        sampler,
        (world, d0),
        d0,
        output_dir=tmp_path,
        hdf5_path=hdf,
        snapshot=snapshot,
        identity={
            "run_id": "run",
            "session_id": "session",
            "episode_id": "episode",
            "source_profile": "isaac_human_vr_offline_rgb_v1",
        },
        observation_factory=observation_factory,
        flush_every_frames=1,
    )
    return live, storage


def test_live_recording_buffers_ot_then_admits_only_committed_row(tmp_path):
    live, storage = make_live(tmp_path)
    token = live.capture_observation()
    assert token.state == Observation.state and token.physics_step == 10
    assert token.observation.capture_sequence == token.capture_sequence
    assert token.observation.scene_state_snapshot_id == token.scene_state_snapshot_id
    assert token.observation.scene_state_snapshot_sha256 == token.scene_state_snapshot_sha256
    successor_token = live.capture_successor(token)
    row = committed_sample()
    row["scene_state_snapshot_id"] = token.scene_state_snapshot_id
    row["scene_state_snapshot_sha256"] = token.scene_state_snapshot_sha256
    row["observation_state"] = np.asarray(token.state, dtype=np.float32)
    row["next_scene_state_snapshot_id"] = successor_token.scene_state_snapshot_id
    row["next_scene_state_snapshot_sha256"] = successor_token.scene_state_snapshot_sha256
    row["successor_observation_state"] = np.asarray(successor_token.state, dtype=np.float32)
    live.commit_transition(token, successor_token, seal_sample(row))
    assert live.committed_frames == storage.advanced == 1
    assert storage.flushed == 1
    with pytest.raises(RuntimeError, match="no pending"):
        live.commit_transition(token, successor_token, row)
    assert live.capture_observation() is successor_token


def test_runtime_builder_uses_causal_receipt_ids_hashes_and_token_snapshot(tmp_path):
    live, _ = make_live(tmp_path)
    token = live.capture_observation()
    successor_token = live.capture_successor(token)
    epoch = SimpleNamespace(
        run_id="run", episode_id="episode", source_id="isaac_human_vr",
        reset_epoch=0, control_reference_epoch=2, source_epoch="7",
    )
    xr = SimpleNamespace(
        session_epoch=7, control_reference_epoch=2, deviceio_update_epoch=3,
        submitted_frame_id=4, returned_frame_id=4, ran_synchronously=True,
        hands=(("left", (1.0, 2.0)), ("right", (3.0, 4.0))),
        world_transform=tuple(np.eye(4, dtype=np.float32).reshape(-1)),
        rebased=False, tracking_valid=(True, True),
    )
    dataset_action = np.arange(14, dtype=np.float32) + 1000
    native_preclip = tuple(np.arange(14) / 10)
    native_clipped = tuple(np.arange(14) / 10)
    observation_sha = hashlib.sha256(token.observation.canonical_payload()).hexdigest()
    successor_sha = hashlib.sha256(successor_token.observation.canonical_payload()).hexdigest()
    action_sha = hashlib.sha256(canonical_action_payload(
        dataset_action,
        processor_revision="processor-v1",
        provenance_revision="provenance-v1",
        processor_generation=5,
    )).hexdigest()
    native_sha = hashlib.sha256(canonical_native_command_payload(
        preclip=native_preclip,
        clipped=native_clipped,
        residual=np.zeros(14),
        saturation=np.zeros(14, dtype=np.uint8),
    )).hexdigest()
    xr_sha = hashlib.sha256(canonical_xr_payload_from_fields(
        session_epoch=xr.session_epoch,
        control_reference_epoch=xr.control_reference_epoch,
        deviceio_update_epoch=xr.deviceio_update_epoch,
        submitted_frame_id=xr.submitted_frame_id,
        returned_frame_id=xr.returned_frame_id,
        ran_synchronously=xr.ran_synchronously,
        rebased=xr.rebased,
        tracking_valid=xr.tracking_valid,
        world_transform=xr.world_transform,
        hands_sha256=canonical_hands_sha256(xr.hands),
    )).hexdigest()

    def identity(payload_id, digest, tick=0):
        return SimpleNamespace(
            epoch=epoch, control_tick_id=tick, payload_id=payload_id, sha256=digest
        )
    prepared = SimpleNamespace(
        observation=identity("obs:0", observation_sha),
        dataset_action=identity("action:0", action_sha),
        sources=(
            SimpleNamespace(name="simulation.scene_state_snapshot", sample=identity("scene:0", observation_sha), sequence=10),
            SimpleNamespace(name="xr.device_io_update", sample=identity("device:0", xr_sha), sequence=3),
            SimpleNamespace(name="xr.submitted_frame", sample=identity("submitted:0", xr_sha), sequence=4),
            SimpleNamespace(name="xr.returned_frame", sample=identity("returned:0", xr_sha), sequence=4),
            SimpleNamespace(name="xr.resolved_input", sample=identity("xr:0", xr_sha), sequence=3),
        ),
    )
    completed = SimpleNamespace(
        native_command=identity("native:0", native_sha),
        transition_id="transition:0",
        successor=identity("obs:1", successor_sha, tick=1),
    )
    committed = SimpleNamespace(
        prepared=prepared, completed=completed, successor_observation=successor_token.observation
    )
    decision = SimpleNamespace(
        observation_identity=token.observation,
        xr_identity=xr,
        dataset_action=dataset_action,
        native_preclip=native_preclip,
        native_clipped=native_clipped,
        residual=tuple(np.zeros(14)),
        saturation=tuple(False for _ in range(14)),
        processor_identity=("processor-v1", "provenance-v1", 5),
    )
    row = build_committed_transition_sample(
        live, token, successor_token, decision, committed
    )
    assert row["obs_id"] == b"obs:0"
    assert row["next_obs_id"] == b"obs:1"
    assert row["scene_state_snapshot_id"] == token.scene_state_snapshot_id.encode()
    assert bytes(row["scene_state_snapshot_sha256"]).hex() == token.scene_state_snapshot_sha256
    assert row["next_scene_state_snapshot_id"] == successor_token.scene_state_snapshot_id.encode()
    assert bytes(row["next_scene_state_snapshot_sha256"]).hex() == successor_token.scene_state_snapshot_sha256
    np.testing.assert_array_equal(row["dataset_action"], np.arange(14) + 1000)


def test_discarded_observation_never_becomes_frame(tmp_path):
    live, storage = make_live(tmp_path)
    token = live.capture_observation()
    live.discard_observation(token, reason="tracking_invalid")
    assert live.committed_frames == storage.advanced == 0
    assert live.discarded_observations == 1
    assert live.rejections == {"tracking_invalid": 1}


def test_close_stream_hashes_and_writes_final_marker_last(tmp_path):
    live, storage = make_live(tmp_path)
    live.close(outcome="operator_stopped")
    marker = json.loads((tmp_path / "recording_state.json").read_text())
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert marker["artifact_state"] == manifest["artifact_state"] == "failed"
    assert marker["outcome"] == "aborted"
    assert marker["reason"] == "zero_committed_transitions"
    assert marker["hdf5_sha256"] == hashlib.sha256(b"hdf").hexdigest()
    assert storage.ended[0][0] is False and storage.closed


def test_commit_error_forces_failed_artifact_even_if_operator_stops(tmp_path):
    live, _ = make_live(tmp_path)
    token = live.capture_observation()
    successor = live.capture_successor(token)
    row = committed_sample()
    row["run_id"] = "wrong-run"
    row["scene_state_snapshot_id"] = token.scene_state_snapshot_id
    row["scene_state_snapshot_sha256"] = token.scene_state_snapshot_sha256
    row["observation_state"] = np.asarray(token.state, dtype=np.float32)
    row["next_scene_state_snapshot_id"] = successor.scene_state_snapshot_id
    row["next_scene_state_snapshot_sha256"] = successor.scene_state_snapshot_sha256
    row["successor_observation_state"] = np.asarray(successor.state, dtype=np.float32)
    with pytest.raises(ValueError, match="active recording"):
        live.commit_transition(token, successor, seal_sample(row))
    live.close(outcome="operator_stopped")
    marker = json.loads((tmp_path / "recording_state.json").read_text())
    assert marker["artifact_state"] == "failed"
    assert marker["outcome"] == "failure"
    assert marker["reason"].startswith("transition_commit_failed:ValueError")


def test_streaming_sha256_matches_reference(tmp_path):
    path = tmp_path / "large.bin"
    payload = bytes(range(256)) * 100
    path.write_bytes(payload)
    assert sha256_file(path, chunk_bytes=17) == hashlib.sha256(payload).hexdigest()


def test_hdf_session_metadata_binds_snapshot_and_asset_closure():
    digest = hashlib.sha256(b"artifact").hexdigest()
    enriched = enrich_recording_session_metadata(
        {
            "run_id": "run",
            "session_id": "session",
            "episode_id": "episode",
            "source_profile": "isaac_human_vr_offline_rgb_v1",
        },
        stage_snapshot="stage_snapshot.usd",
        stage_snapshot_sha256=digest,
        asset_closure_sha256=digest,
    )
    assert enriched["stage_snapshot"] == "stage_snapshot.usd"
    assert enriched["stage_snapshot_sha256"] == digest
    assert enriched["asset_closure_sha256"] == digest
    with pytest.raises(ValueError, match="artifact-relative"):
        enrich_recording_session_metadata(
            enriched,
            stage_snapshot="../stage_snapshot.usd",
            stage_snapshot_sha256=digest,
            asset_closure_sha256=digest,
        )


def test_recording_writes_atomic_portable_asset_closure_sidecar(tmp_path):
    snapshot = tmp_path / "stage_snapshot.usd"
    dependency = tmp_path / "assets" / "texture.png"
    dependency.parent.mkdir()
    snapshot.write_bytes(b"stage")
    dependency.write_bytes(b"pixels")
    sidecar = tmp_path / "asset_closure.json"
    closure = write_asset_closure_sidecar(
        snapshot,
        sidecar,
        portable_roots={"recording": tmp_path},
        dependency_provider=lambda _snapshot: ((), (dependency,), ()),
    )
    assert json.loads(sidecar.read_text()) == closure
    assert closure["stage_snapshot_path"] == "recording/stage_snapshot.usd"
    assert len(closure["asset_closure_sha256"]) == 64


def test_private_output_path_validation(tmp_path):
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    repository = tmp_path / "repo"
    repository.mkdir()
    output = prepare_private_output_dir(parent / "episode", repository=repository, min_free_bytes=0)
    assert output.is_dir() and (output.stat().st_mode & 0o777) == 0o700
    with pytest.raises(FileExistsError):
        prepare_private_output_dir(output, repository=repository, min_free_bytes=0)


def test_private_output_rejects_relative_permissive_and_repo_paths(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(ValueError, match="absolute"):
        prepare_private_output_dir(Path("relative"), repository=repository, min_free_bytes=0)
    permissive = tmp_path / "permissive"
    permissive.mkdir(mode=0o755)
    permissive.chmod(0o755)
    with pytest.raises(PermissionError, match="group/other"):
        prepare_private_output_dir(permissive / "episode", repository=repository, min_free_bytes=0)
    repository.chmod(0o700)
    with pytest.raises(ValueError, match="outside"):
        prepare_private_output_dir(repository / "episode", repository=repository, min_free_bytes=0)


def test_private_output_rejects_wrong_owner_and_insufficient_space(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    actual_uid = parent.stat().st_uid
    monkeypatch.setattr("tools.isaac_vr_recording.os.getuid", lambda: actual_uid + 1)
    with pytest.raises(PermissionError, match="current uid"):
        prepare_private_output_dir(parent / "wrong-owner", repository=repository, min_free_bytes=0)

    monkeypatch.setattr("tools.isaac_vr_recording.os.getuid", lambda: actual_uid)
    monkeypatch.setattr(
        "tools.isaac_vr_recording.shutil.disk_usage",
        lambda path: SimpleNamespace(free=7),
    )
    with pytest.raises(OSError, match="insufficient recording disk space"):
        prepare_private_output_dir(parent / "too-large", repository=repository, min_free_bytes=8)


def test_replay_guard_applies_order_without_physics_or_native_actions():
    applied, pumps = [], []

    class Replayer:
        def apply_frame(self, frame):
            applied.append(frame)

    apply_replay_frames(Replayer(), 3, pump=lambda: pumps.append(True), physics_steps=lambda: 42)
    assert applied == [0, 1, 2] and len(pumps) == 3

    with pytest.raises(RuntimeError, match="advanced physics"):
        calls = iter((42, 43))
        apply_replay_frames(Replayer(), 1, pump=lambda: None, physics_steps=lambda: next(calls))
