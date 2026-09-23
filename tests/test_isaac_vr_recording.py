"""Pure-Python contract tests for the explicit NVIDIA V2 frame coordinator."""

from types import SimpleNamespace

import numpy as np
import pytest

from tools.isaac_vr_recording import ExplicitFrameSampler, _d0_channels, _empty_d0_sample
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
    sampler = ExplicitFrameSampler(storage, (FakeRecordable("world", 0), FakeRecordable("d0/transition", 1000)))
    sampler.sample_frame()
    assert storage.advanced == 1
    assert storage.frames == [("world", {"marker": np.int64(0)}), ("d0/transition", {"marker": np.int64(1000)})]


def test_failed_recordable_never_advances_and_fails_closed():
    storage = FakeStorage()
    sampler = ExplicitFrameSampler(storage, (FakeRecordable("world", 0), FakeRecordable("d0", 1, broken=True)))
    with pytest.raises(RuntimeError, match="sample failed"):
        sampler.sample_frame()
    assert storage.advanced == 0
    with pytest.raises(RuntimeError, match="failed closed"):
        sampler.sample_frame()


def test_d0_schema_has_fixed_numeric_o0_and_transition_channels():
    class Descriptor:
        def __init__(self, *, shape, dtype):
            self.shape, self.dtype = shape, dtype

    channels = _d0_channels(Descriptor)
    sample = _empty_d0_sample()
    assert channels["observation_state"].shape == channels["dataset_action"].shape == (14,)
    assert sample["observation_id"] == -1 and sample["action_valid"] == 0
    assert sample["action_from_observation_id"] == sample["action_to_observation_id"] == -1
    for name, value in sample.items():
        assert np.asarray(value).shape == channels[name].shape
        assert np.issubdtype(np.asarray(value).dtype, np.number)


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


@pytest.mark.parametrize("group,plural", [("state/left_robot", True), ("state/right_robot", True), ("state/object_0", False)])
@pytest.mark.parametrize("corrupt", ["fallback", "quaternion", "nonfinite", "read_error"])
def test_required_world_pose_fails_closed(group, plural, corrupt):
    from tools.isaac_vr_recording import validate_world_pose

    positions = np.array([[0.25, 0.0, 0.75]], np.float32)
    orientations = np.array([[1, 0, 0, 0]], np.float32)
    keys = ("positions", "orientations") if plural else ("position", "orientation")
    frame = dict(zip(keys, (positions.copy(), orientations.copy()) if plural else
                     (positions[0].copy(), orientations[0].copy()), strict=True))
    validate_world_pose(group, frame, positions, -orientations)  # Legal zeros and quaternion sign.
    if corrupt == "fallback":
        frame[keys[0]][...] = 0  # Upstream fallback is zero position + UNIT quaternion.
    elif corrupt == "quaternion":
        frame[keys[1]][...] = 0
    elif corrupt == "nonfinite":
        frame[keys[0]][...] = np.nan

    recordable = SimpleNamespace(
        group=group, sample=lambda: frame,
        describe_channels=lambda: {k: SimpleNamespace(shape=v.shape, dtype="f4") for k, v in frame.items()},
    )
    storage = FakeStorage()
    sampler = ExplicitFrameSampler(storage, [recordable])

    def independent_read():
        if corrupt == "read_error":
            raise RuntimeError("Fabric read failed")
        return positions, orientations

    sampler.pose_readers[group] = independent_read
    with pytest.raises((ValueError, RuntimeError)):
        sampler.sample_frame()
    assert sampler.failed and storage.advanced == 0 and not storage.frames


def test_partial_append_closes_as_failed_with_complete_prefix_metadata(tmp_path):
    import json
    from tools.isaac_vr_recording import LiveRecording

    storage = FakeStorage()
    storage.end_episode = lambda **kw: metadata.append(kw["metadata"])
    storage.close = lambda: None
    a, b = FakeRecordable("A", 0), FakeRecordable("B", 1)
    for rec in (a, b):
        rec.on_episode_end = rec.on_session_close = lambda: None
    sampler = ExplicitFrameSampler(storage, [a, b])
    hdf5 = tmp_path / "session.hdf5"
    hdf5.write_bytes(b"mock trimmed prefix")
    (tmp_path / "manifest.json").write_text("{}")
    metadata = []
    recording = LiveRecording(storage, sampler, [a, b], SimpleNamespace(set_sample=lambda x: None),
                              output_dir=tmp_path, hdf5_path=hdf5, snapshot=tmp_path / "stage_snapshot.usd")
    recording.sample({"observation_id": 0})
    original_append = storage.append_frame

    def partial_append(group, frame):
        if group == "B":
            raise RuntimeError("injected append failure")
        original_append(group, frame)

    storage.append_frame = partial_append
    with pytest.raises(RuntimeError, match="append failure") as error:
        recording.sample({"observation_id": 1})
    assert len(storage.frames) == 3 and storage.advanced == 1
    recording.close(outcome="runtime_failed", failure={"exception_type": "RuntimeError", "message": str(error.value)})
    assert metadata[0]["outcome"] == "runtime_failed"
    assert metadata[0]["last_complete_observation"] == 0
    assert metadata[0]["complete_frames"] == 1
    assert json.loads((tmp_path / "manifest.json").read_text())["outcome"] == "runtime_failed"


def test_native_episode_segmentation_uses_public_lifecycle(tmp_path):
    from tools.isaac_vr_recording import LiveRecording
    calls = []
    storage = SimpleNamespace(
        end_episode=lambda **kw: calls.append(("end", kw)),
        begin_episode=lambda *a, **kw: calls.append(("begin", kw)) or 1,
    )
    recordable = FakeRecordable("state", 1)
    recordable.on_episode_end = lambda: calls.append(("recordable_end",))
    recordable.on_episode_start = lambda: calls.append(("recordable_start",))
    sampler = ExplicitFrameSampler(storage, [recordable])
    recording = LiveRecording(storage, sampler, [recordable], None, output_dir=tmp_path,
                              hdf5_path=tmp_path / "session.hdf5", snapshot=tmp_path / "stage_snapshot.usd")
    recording.last_complete_observation = 8
    recording.segment(reason="reset")
    assert [c[0] for c in calls] == ["recordable_end", "end", "begin", "recordable_start"]
    assert calls[1][1]["metadata"] == {"outcome": "completed", "boundary": "reset"}
    assert recording.episode_index == 1 and recording.last_complete_observation is None
