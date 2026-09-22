"""Deterministic injected-XR recorder seam tests without Kit."""

from pathlib import Path
import sys

import numpy as np


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


class FakeEnvironment:
    def __init__(self):
        self.physics_step = 20
        self.state = np.asarray(
            [-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0] * 2,
            dtype=np.float32,
        )
        self.pending = None

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

    def __init__(self, env):
        self.env = env
        self.committed_frames = 0
        self.sequence = 0
        self.promoted = None
        self.rows = []

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

    def commit_transition(self, token, successor, row):
        canonical = canonical_committed_transition(row)
        verify_committed_transition_sample(canonical)
        assert int(canonical["frame_index"]) == self.committed_frames
        self.rows.append(canonical)
        self.committed_frames += 1
        self.promoted = successor


def test_injected_transitions_are_distinct_dense_and_self_verifying():
    env = FakeEnvironment()
    recording = FakeRecording(env)
    result = record_injected_transitions(recording, env, count=3)

    assert result["accepted_transactions"] == result["committed_frames"] == 3
    assert len({tuple(action) for action in result["actions"]}) == 3
    assert [int(row["frame_index"]) for row in recording.rows] == [0, 1, 2]
    for current, following in zip(recording.rows, recording.rows[1:], strict=False):
        assert np.array_equal(
            current["successor_observation_state"],
            following["observation_state"],
        )
