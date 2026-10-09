"""CPU-only bounded producer queue; no worker process or GPU is launched."""

import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/experiments/20261009_live_camera_recording_30hz/deep_research/live_mirror.py"
)
spec = importlib.util.spec_from_file_location("source_queue_test", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
LiveMirror = module.LiveMirror


def mirror(capacity):
    m = LiveMirror.__new__(LiveMirror)
    m.capacity, m.encoder_capacity = capacity, 8
    m.source_clock, m.reset_epoch, m.last_physics, m.intrinsics = None, None, None, None
    m.pending, m.sent, m.acked, m.max_pending, m.blocked_ms, m.ages_ms = {}, 0, 0, 0, 0.0, []
    m.metadata = {"witness": False}
    m.pose = lambda p, q: np.eye(4)
    m.entries = [{"group": "state/camera/" + role, "type": "camera"} for role in module.ROLES]
    frames = {"meta/time": {"sim_time": 1.0, "wall_time": 1.0}}
    frames.update(
        {
            e["group"]: {
                "position": [0, 0, 0],
                "orientation": [1, 0, 0, 0],
                "focal_length": 1.0,
                "horizontal_aperture": 2.0,
                "vertical_aperture": 3.0,
            }
            for e in m.entries
        }
    )
    m.original = lambda: (
        SimpleNamespace(
            capture_sequence=m.sent,
            reset_epoch=1,
            physics_step=120 + 4 * m.sent,
            state_generation=120 + 4 * m.sent,
            scene_state_snapshot_id=str(m.sent),
            scene_state_snapshot_sha256="x",
        ),
        frames,
    )

    class Conn:
        def __init__(self):
            self.sent, self.received, self.fail = [], 0, False

        def poll(self, timeout=0):
            return bool(timeout)  # ACK is available only when backpressure explicitly waits.

        def send(self, payload):
            self.sent.append(dict(payload))

        def recv(self):
            if self.fail:
                return {"kind": "error", "error": "injected worker failure"}
            seq = self.sent[self.received]["source_id"]
            self.received += 1
            return {"kind": "ack", "source_id": seq}

    m.conn = Conn()
    return m


@pytest.mark.parametrize("capacity", [1, 8])
def test_backpressure_keeps_every_immutable_source_once(capacity):
    m = mirror(capacity)
    for _ in range(20):
        m.capture()
        assert len(m.pending) <= capacity
    assert [x["source_id"] for x in m.conn.sent] == list(range(20))
    assert [x["snapshot_id"] for x in m.conn.sent] == [str(i) for i in range(20)]
    assert m.max_pending == capacity and m.acked == 20 - capacity
    assert sorted(m.pending) == list(range(20 - capacity, 20))
    assert m.encoder_capacity == 8


def test_worker_failure_blocks_new_send_without_overwrite_or_drop():
    m = mirror(1)
    m.capture()
    first = m.pending[0]
    m.conn.fail = True
    with pytest.raises(RuntimeError, match="injected worker failure"):
        m.capture()
    assert m.pending[0] is first and list(m.pending) == [0]
    assert m.sent == 1 and len(m.conn.sent) == 1


@pytest.mark.parametrize("capacity", [0, 2, 9, True, 1.0])
def test_invalid_opt_in_queue_rejected_before_any_resources(capacity, tmp_path):
    with pytest.raises(ValueError, match="Source queue capacity"):
        LiveMirror(
            SimpleNamespace(_next_capture_sequence=0),
            tmp_path / "out",
            source_queue_capacity=capacity,
        )
    assert not (tmp_path / "out").exists()


def test_default_source_and_native_owner_capacity_remain_eight():
    parameters = inspect.signature(LiveMirror).parameters
    assert parameters["source_queue_capacity"].default == parameters["capacity"].default == 8
