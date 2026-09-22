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
