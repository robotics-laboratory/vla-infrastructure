"""Public event shape and ambiguous handle joins; no GPU/resource lifetime claim."""
from collections import deque
import importlib.util
from pathlib import Path
import threading

SOURCE = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_deep/managed_event_probe.py"
spec = importlib.util.spec_from_file_location("managed_probe_cpu", SOURCE)
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


class Event:
    """Installed pybind get accepts one argument, unlike dict.get's overload."""
    def __init__(self, values):
        self.values = values
    def get(self, key):
        return self.values.get(key)
    def __getitem__(self, key):
        return self.values[key]


def test_native_event_get_is_single_argument():
    assert probe_module._event_value(Event({"results": 7}), "results") == 7
    assert probe_module._event_value(Event({}), "missing") is None


def probe():
    p = probe_module.ManagedEventProbe.__new__(probe_module.ManagedEventProbe)
    p.lock = threading.RLock()
    p.closed = False
    p.errors = []
    p.counters = dict.fromkeys(("new_frame", "drawable", "sd"), 0)
    p.dropped_history = dict.fromkeys(p.counters, 0)
    p.history = {key: deque(maxlen=3) for key in p.counters}
    p.holders = {"left": []}
    p.subscriptions = []
    return p


def test_reused_native_pointer_is_preserved_as_an_ambiguous_join():
    p = probe()
    for frame in (10, 11):
        p._on_new_frame(Event(dict(results=12345, viewport_handle=5,
                                  frame_number=frame, swh_frame_number=frame + 61)))
        p._append("drawable", dict(role="left", viewport_handle=5,
            frame_info=dict(frame_number=frame, swh_frame_number=frame+61)))
    p.observe_sd(dict(role="left", render_product="/Product",
                     render_result_handle_diagnostic=12345,
                     frame_identifier={"frameNumber": 72, "type": "FrameNumber"},
                     producer_cuda_stream=7))
    receipt = p.receipt()
    join = receipt["candidate_joins"][0]
    assert len(join["scalar_matching_drawable_candidates"]) == 2
    assert join["ambiguous_or_missing"]
    assert len(join["identifier_confirmed_candidates"]) == 1
    assert not receipt["source_binding_proven"]
    assert not receipt["same_recorded_preview_pixels_proven"]
    assert not receipt["actual_ui_presented"]


def test_bounded_history_loss_is_explicit():
    p = probe()
    for frame in range(4):
        p._on_new_frame(Event(dict(results=frame, viewport_handle=1,
                                  frame_number=frame, swh_frame_number=frame)))
    assert p.receipt()["dropped_history"]["new_frame"] == 1
    p.close()
    p._on_new_frame(Event(dict(results=99)))
    assert p.receipt()["counters"]["new_frame"] == 4
