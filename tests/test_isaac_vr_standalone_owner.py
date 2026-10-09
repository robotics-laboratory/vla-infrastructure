"""CPU owner invariants against actual production methods; no native runtime."""

import json
from pathlib import Path
import sys
import threading
import types
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from isaac_vr_standalone import StandaloneState
from isaac_vr_standalone_ik import BODIES, DOFS


class Sim:
    def __init__(self):
        self.native_step = 100

    def get_physics_step_count(self):
        return self.native_step


def snapshot(seq=-1):
    poses = np.zeros((27, 7), np.float32)
    poses[:, 6] = 1
    com = np.zeros((2, 12, 7), np.float32)
    com[:, :, 6] = 1
    return dict(
        seq=seq,
        physics_steps=4 * (seq + 1),
        sim_time_s=4 * (seq + 1) / 120,
        fixed_base=True,
        q=np.zeros((2, 9), np.float32),
        dq=np.zeros((2, 9), np.float32),
        rigid_body_world_pose=poses,
        articulation_body_com_local_pose=com,
        jacobian=np.zeros((2, 66, 9), np.float32),
        root_pose=poses[[0, 12]].copy(),
        mimic_residual=np.zeros((2, 2), np.float32),
    )


@pytest.fixture
def owner(tmp_path):
    env = types.SimpleNamespace(
        sim=Sim(),
        camera=types.SimpleNamespace(reset_epoch=7),
        _state_physics_step=100,
        joint_ids=[list(range(7))] * 2,
        actuated_joint_ids=[list(range(9))] * 2,
        _with_mimics=lambda values: np.concatenate([values, [0.5 * values[6], -0.5 * values[6]]]),
    )
    obj = StandaloneState(env, tmp_path / "physics", python="/unused/no-native-runtime")
    obj.seed = dict(body_names=list(BODIES), dof_names=list(DOFS))
    obj.properties = dict(limits=np.tile(np.asarray([-1, 1], np.float32), (2, 9, 1)))
    obj.targets = np.zeros((2, 9), np.float32)
    obj._accept(snapshot(), initial=True)
    yield obj
    if vars(env.sim).get("get_physics_step_count") is obj.clock._override:
        obj.clock.close()


def test_owner_preserves_current_canonical_reset_epoch(owner):
    assert owner.clock.epoch == owner.env.camera.reset_epoch


def test_accepted_arrays_are_independent_readonly_and_ik_uses_same_snapshot(owner):
    incoming = snapshot(0)
    original_q = incoming["q"]
    owner._accept(incoming)
    original_q[:] = 999
    assert np.array_equal(owner.snapshot["q"], np.zeros((2, 9)))
    assert np.array_equal(owner._ik["q"], owner.snapshot["q"][:, :6])
    for value in owner.snapshot.values():
        if isinstance(value, np.ndarray):
            assert not value.flags.writeable
    for value in owner._ik.values():
        assert not value.flags.writeable


def test_invalid_ik_snapshot_cannot_replace_last_completed_source(owner):
    before, before_seq = owner.snapshot, owner.seq
    broken = snapshot(0)
    broken["rigid_body_world_pose"][:, 6] = 2  # invalid native unit quaternion
    with pytest.raises(ValueError, match="nonunit"):
        owner._accept(broken)
    assert owner.snapshot is before
    assert owner.seq == before_seq


@pytest.mark.parametrize("field,value", [("seq", 2), ("physics_steps", 8), ("fixed_base", False)])
def test_bad_completed_identity_rejected_without_clock_or_snapshot_change(owner, field, value):
    before = owner.snapshot
    bad = snapshot(0)
    bad[field] = value
    with pytest.raises(RuntimeError):
        owner._accept(bad)
    assert owner.snapshot is before
    assert owner.clock.physics_step == 100


def test_nonfinite_and_mimic_divergence_reject_source(owner):
    for field, value in [("jacobian", float("nan")), ("mimic_residual", 0.001)]:
        incoming = snapshot(0)
        incoming[field].flat[0] = value
        with pytest.raises(RuntimeError):
            owner._accept(incoming)
        assert owner.seq == -1


def test_apply_maps_mimics_without_advancing_source_or_mutating_input(owner):
    left = np.asarray([1, 2, 3, 4, 5, 6, 0.04], np.float32)
    right = -left
    right[6] = 0.06
    command = types.SimpleNamespace(left_rad_m=left, right_rad_m=right)
    left_before, right_before = left.copy(), right.copy()
    owner.apply(command)
    np.testing.assert_allclose(owner.targets[0], [*left, 0.02, -0.02])
    np.testing.assert_allclose(owner.targets[1], [*right, 0.03, -0.03])
    assert np.array_equal(left, left_before) and np.array_equal(right, right_before)
    assert owner.clock.physics_step == 100 and owner.seq == -1


class Connection:
    def __init__(self, reply):
        self.reply, self.sent, self.closed = reply, [], False

    def send(self, message):
        self.sent.append(message)

    def poll(self, timeout):
        return True

    def recv(self):
        return self.reply

    def close(self):
        self.closed = True


class Process:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def configure_reply(owner, targets=None):
    owner.proc = Process()
    owner.conn = Connection(
        dict(
            op="captured",
            native_targets=owner.targets.copy() if targets is None else targets,
            snapshot=snapshot(0),
            timings_ns=dict(target=1, physics4=2, capture=3, total=6),
        )
    )
    seen = []
    owner.resolver = types.SimpleNamespace(poses=lambda paths, values: values.copy())
    owner.view = types.SimpleNamespace(
        paths=["/fake"] * 27,
        update=lambda poses, verify_readback: seen.append(
            (owner.clock.physics_step, owner.seq, poses.copy())
        ),
    )
    return seen


def test_completed_four_substeps_publish_clock_before_passive_view(owner):
    seen = configure_reply(owner)
    with patch("isaac_vr_standalone.time.time", return_value=123.5):
        owner.advance(4)
    assert owner.conn.sent[0]["op"] == "step" and owner.conn.sent[0]["seq"] == 0
    assert seen[0][:2] == (104, 0)
    assert owner.env._state_physics_step == 104
    with patch("isaac_vr_standalone_view.time.time", return_value=124.0):
        assert owner.clock.sample() == dict(physics_step=104, sim_time=104 / 120, wall_time=124.0)
    assert owner.clock.wall_time == 123.5
    assert owner.clock.state_received_origin == "physics_reply_received"
    assert owner.clock.state_received_monotonic_ns <= owner.clock.observation_sample_monotonic_ns
    assert owner.receipt["controls"] == 1


def test_sampling_time_advances_without_refreshing_frozen_state_age(owner):
    state_time = owner.clock.state_received_monotonic_ns
    state_wall = owner.clock.wall_time
    with patch("isaac_vr_standalone_view.time.time", side_effect=[300.0, 299.0]):
        first, second = owner.sample_time(), owner.sample_time()
    assert first["wall_time"] == 300.0 and second["wall_time"] == 299.0
    assert first["physics_step"] == second["physics_step"] == 100
    assert owner.clock.state_received_monotonic_ns == state_time
    assert owner.clock.wall_time == state_wall
    assert owner.clock.state_received_origin == "initial_native_freeze"
    assert owner.clock.observation_sample_monotonic_ns >= state_time


def test_wrong_command_ack_cannot_publish_snapshot_clock_or_view(owner):
    seen = configure_reply(owner, np.ones((2, 9), np.float32))
    before = owner.snapshot
    with pytest.raises(RuntimeError, match="acknowledgment"):
        owner.advance(4)
    assert owner.snapshot is before and owner.clock.physics_step == 100
    assert not seen and owner.receipt["controls"] == 0


def test_native_engine_movement_rejects_sample_apply_and_step_before_ipc(owner):
    configure_reply(owner)
    owner.env.sim.native_step += 1
    with pytest.raises(RuntimeError, match="native SimContext"):
        owner.sample_time()
    with pytest.raises(RuntimeError, match="native SimContext"):
        owner.advance(4)
    with pytest.raises(RuntimeError, match="native SimContext|failed closed"):
        owner.apply(types.SimpleNamespace(left_rad_m=np.zeros(7), right_rad_m=np.zeros(7)))
    assert owner.conn.sent == []


def test_clock_rejects_gap_epoch_and_nonfinite_wall_time(owner):
    for epoch, step, wall in [
        (owner.clock.epoch, 108, 1),
        (owner.clock.epoch + 1, 104, 1),
        (owner.clock.epoch, 104, float("nan")),
    ]:
        with pytest.raises((RuntimeError, ValueError)):
            owner.clock.commit(epoch=epoch, physics_step=step, captured_wall_time=wall)
        assert owner.clock.physics_step == 100


def test_start_failure_still_allows_clock_restoration_and_owner_receipt(owner):
    def fail(*args):
        raise ValueError("invalid seed before native startup")

    with patch.dict(
        sys.modules,
        {
            "isaac_vr_standalone_scene": types.SimpleNamespace(
                build_seed=fail, SnapshotPoses=object
            ),
            "isaacsim.core.simulation_manager": types.SimpleNamespace(SimulationManager=object),
        },
    ):
        with pytest.raises(ValueError, match="invalid seed"):
            owner.start("/unused-stage")
    owner.close()
    assert "get_physics_step_count" not in vars(owner.env.sim)
    assert json.loads((owner.output / "owner.json").read_text())["controls"] == 0


def test_close_restores_instance_overrides_and_completed_child(owner):
    previous = object()
    owner.env._apply = previous
    owner._override("_apply", owner.apply)
    owner._override("standalone_state", owner)
    owner.proc = Process()
    owner.conn = Connection(dict(op="closed", controls=0, physics_steps=0))
    owner.close()
    assert owner.env._apply is previous
    assert not hasattr(owner.env, "standalone_state")
    assert owner.conn.closed and owner.proc.returncode == 0
    assert "get_physics_step_count" not in vars(owner.env.sim)


def test_close_rejects_wrong_terminal_reply_but_restores_clock(owner):
    owner.proc = Process()
    owner.conn = Connection(dict(op="captured"))
    with pytest.raises(RuntimeError):
        owner.close()
    assert "get_physics_step_count" not in vars(owner.env.sim)
    assert json.loads((owner.output / "owner.json").read_text())["cleanup_errors"]


def test_close_rejects_nonzero_child_exit_but_restores_clock(owner):
    class FailedProcess(Process):
        def wait(self, timeout):
            self.returncode = 1
            return 1

    owner.proc = FailedProcess()
    owner.conn = Connection(dict(op="closed", controls=0, physics_steps=0))
    with pytest.raises(RuntimeError):
        owner.close()
    assert "get_physics_step_count" not in vars(owner.env.sim)
    assert json.loads((owner.output / "owner.json").read_text())["cleanup_errors"]


def test_clock_rejects_cross_thread_sampling(owner):
    failures = []

    def sample():
        try:
            owner.sample_time()
        except RuntimeError as error:
            failures.append(str(error))

    thread = threading.Thread(target=sample)
    thread.start()
    thread.join()
    assert len(failures) == 1 and "owner thread" in failures[0]
    assert owner.clock.physics_step == 100
