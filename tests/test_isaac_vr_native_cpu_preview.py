"""CPU-only ownership checks for the finite native preview transport."""

from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
import weakref

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from isaac_vr_native_cpu_preview import CpuPreviewProbe


@pytest.fixture
def backend(monkeypatch):
    state = SimpleNamespace(events=[], pending=[], active=None, probe=None)

    class Tensor:
        dtype = "uint8"
        ndim = 3

        def __init__(self, array, device="cuda:0"):
            self.array, self.device = array, device
            self.shape = array.shape

        def is_contiguous(self):
            return self.array.flags.c_contiguous

        def copy_(self, source, *, non_blocking):
            assert non_blocking and state.active is state.probe.stream
            state.events.append("copy")
            # A copy does not complete until the scoped event is synchronized.
            state.pending.append(lambda: np.copyto(self.array, source.array))

        def numpy(self):
            assert not state.pending, "CPU read preceded D2H completion"
            state.events.append("cpu_read")
            return self.array

    class Event:
        def __init__(self, *, enable_timing):
            assert enable_timing is False

        def record(self, stream):
            assert state.active is stream
            state.events.append("record")

        def synchronize(self):
            state.events.append("event_sync")
            for copy in state.pending:
                copy()
            state.pending.clear()

    @contextmanager
    def activate(stream):
        state.active = stream
        yield
        state.active = None

    def empty(shape, *, dtype, device, pin_memory):
        assert (dtype, device, pin_memory) == ("uint8", "cpu", True)
        state.events.append("allocate_pinned")
        return Tensor(np.full(shape, 251, dtype=np.uint8), device)

    def forbidden_context_sync(*args, **kwargs):
        raise AssertionError("Transport must not synchronize the CUDA context")

    fake_torch = SimpleNamespace(
        device=lambda device: device, uint8="uint8", empty=empty,
        cuda=SimpleNamespace(
            Stream=lambda *, device: object(), Event=Event, stream=activate,
            synchronize=forbidden_context_sync,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    class Provider:
        def __init__(self):
            self.calls = []
            self.fail = False

        def set_data_array(self, payload, sizes, *, strict):
            assert not state.pending
            assert state.probe.submitted[-1][self.role] is payload
            assert strict is True
            state.events.append("upload")
            self.calls.append((payload, sizes))
            if self.fail:
                raise RuntimeError("provider failed after borrowing payload")

    providers = {role: Provider() for role in ("left", "right", "scene")}
    for role, provider in providers.items():
        provider.role = role

    def make_probe(budget=3):
        state.probe = CpuPreviewProbe(
            providers, cuda_device="cuda:0", max_publications=budget
        )
        return state.probe

    def images(value=17):
        return {
            role: Tensor(np.full((2, 3, 4), value + index, dtype=np.uint8))
            for index, role in enumerate(providers)
        }

    return SimpleNamespace(
        state=state, providers=providers, make_probe=make_probe, images=images
    )


def test_all_copies_finish_before_cpu_access_or_provider_upload(backend):
    probe = backend.make_probe()
    frames = backend.images()
    probe.publish_producer_complete(frames)
    events = backend.state.events
    assert events.count("copy") == 3
    assert events.count("event_sync") == 1
    assert max(i for i, event in enumerate(events) if event == "copy") < events.index("record")
    assert events.index("record") < events.index("event_sync") < events.index("cpu_read")
    assert max(i for i, event in enumerate(events) if event == "cpu_read") < events.index("upload")
    for role, provider in backend.providers.items():
        payload, sizes = provider.calls[0]
        assert sizes == [3, 2]
        np.testing.assert_array_equal(payload, frames[role].array.reshape(-1))


def test_reused_pinned_staging_cannot_mutate_retained_provider_payload(backend):
    probe = backend.make_probe()
    frames = backend.images()
    probe.publish_producer_complete(frames)
    initial = dict(probe.submitted[0])
    expected = {role: value.copy() for role, value in initial.items()}
    staging = dict(probe.staging)
    for image in frames.values():
        image.array.fill(91)
    probe.publish_producer_complete(frames)
    assert all(probe.staging[role] is value for role, value in staging.items())
    assert backend.state.events.count("allocate_pinned") == 3
    for role, payload in initial.items():
        np.testing.assert_array_equal(payload, expected[role])
        assert not np.shares_memory(payload, staging[role].array)
        assert not np.shares_memory(payload, probe.submitted[1][role])
        with pytest.raises(ValueError, match="read-only"):
            payload[0] = 0


def test_provider_failure_retains_every_submission_before_any_borrow(backend):
    probe = backend.make_probe()
    backend.providers["right"].fail = True
    with pytest.raises(RuntimeError, match="provider failed"):
        probe.publish_producer_complete(backend.images())
    assert len(probe.submitted) == 1
    assert set(probe.submitted[0]) == set(backend.providers)
    assert len(backend.providers["left"].calls) == 1
    assert len(backend.providers["right"].calls) == 1
    assert backend.providers["scene"].calls == []
    for role in ("left", "right"):
        assert backend.providers[role].calls[0][0] is probe.submitted[0][role]


def test_budget_exhaustion_has_no_copy_or_upload_and_preserves_previous_payload(backend):
    probe = backend.make_probe(budget=1)
    frames = backend.images()
    probe.publish_producer_complete(frames)
    refs = {role: weakref.ref(payload) for role, payload in probe.submitted[0].items()}
    for provider in backend.providers.values():
        provider.calls.clear()
    backend.state.events.clear()
    with pytest.raises(RuntimeError, match="budget exhausted"):
        probe.publish_producer_complete(frames)
    assert backend.state.events == []
    assert all(ref() is probe.submitted[0][role] for role, ref in refs.items())
    # The probe has no close method: the enclosing Kit owner holds it until app shutdown.
    assert not hasattr(probe, "close")


@pytest.mark.parametrize("invalid", ["missing_role", "wrong_device", "wrong_dtype"])
def test_invalid_triplet_never_reaches_copy_or_provider(backend, invalid):
    probe = backend.make_probe()
    frames = backend.images()
    if invalid == "missing_role":
        frames.pop("right")
    elif invalid == "wrong_device":
        frames["right"].device = "cpu"
    else:
        frames["right"].dtype = "float32"
    with pytest.raises(ValueError):
        probe.publish_producer_complete(frames)
    assert "copy" not in backend.state.events
    assert "upload" not in backend.state.events
    assert probe.submitted == []
