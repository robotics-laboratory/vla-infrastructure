"""CPU mocks only: no torch import, no libcuda load, no Kit execution."""
import ctypes
import gc
import types
import weakref

import pytest
from tools.isaac_vr_native_copy_queue import CopyReceipt, ProviderCopyQueue


class Owner:
    shape = (600, 960, 4)
    dtype = "torch.uint8"
    device = types.SimpleNamespace(type="cuda")
    def __init__(self, pointer=0x123):
        self.pointer = pointer
    def data_ptr(self):
        return self.pointer
    def is_contiguous(self):
        return True


class Fake:
    def __init__(self):
        self.layout = None
        self.copy = None
        self.active = False
        self.next_event = 100
        self.events = {}
        self.calls = []
        self.lookups = 1
        self.competing = 0
        self.begin_result = 0
        self.end_result = 0
        self.release_result = 0
        self.released = []
    def vla_copy_probe_receipt_size(self):
        return ctypes.sizeof(CopyReceipt)
    def vla_copy_probe_competing_bindings(self):
        return self.competing
    def vla_copy_probe_intercepted_lookups(self):
        return self.lookups
    def vla_copy_probe_begin(self, *layout):
        self.calls.append("begin")
        assert not self.active
        if self.begin_result:
            return self.begin_result
        self.active = True
        self.layout = layout
        self.copy = CopyReceipt(0, 0, *layout, 0, -1, -2)
        return 0
    def setter(self, *, matched=1, context=0x10, fence=0, result=0):
        assert self.active
        self.calls.append("setter")
        if matched:
            event = self.next_event
            self.next_event += 1
            self.events[event] = 600
            self.copy.event, self.copy.context = event, context
            self.copy.matched_calls, self.copy.fence_status = matched, fence
            self.copy.copy_result = result
    def vla_copy_probe_end(self, out):
        self.calls.append("end")
        assert self.active
        self.active = False
        ctypes.memmove(out, ctypes.byref(self.copy), ctypes.sizeof(self.copy))
        return self.end_result
    def vla_copy_probe_query(self, event, context):
        self.calls.append(("query", event, context))
        return self.events[event]
    def vla_copy_probe_release(self, event, context):
        self.calls.append(("release", event, context))
        if self.release_result:
            return self.release_result
        assert self.events[event] == 0
        del self.events[event]
        self.released.append(event)
        return 0


def make(**kwargs):
    api = Fake()
    return ProviderCopyQueue(api=api, **kwargs), api


def test_pending_owner_is_retained_until_successful_query_and_release():
    q, api = make()
    owner = Owner()
    ref = weakref.ref(owner)
    r = q.upload(owner, api.setter)
    del owner
    gc.collect()
    assert ref() is not None
    assert api.calls == ["begin", "setter", "end"]
    assert q.poll() == 0 and ref() is not None and not api.released
    api.events[r["event"]] = 0
    assert q.poll() == 1
    gc.collect()
    assert ref() is None
    assert api.released == [r["event"]]
    assert q.receipt()["released"] == 1


def test_budget_is_checked_before_begin_without_borrowing_new_owner():
    q, api = make(max_pending=1)
    q.upload(Owner(), api.setter)
    calls = list(api.calls)
    new_owner = Owner(456)
    ref = weakref.ref(new_owner)
    with pytest.raises(RuntimeError, match="budget"):
        q.upload(new_owner, api.setter)
    assert api.calls == calls and len(q.pending) == 1
    del new_owner
    gc.collect()
    assert ref() is None
    with pytest.raises(RuntimeError, match="budget"):
        q.poll()


@pytest.mark.parametrize("case", ["missing", "extra", "lookup", "competing",
                                     "context", "fence", "copy", "layout", "end"])
def test_invalid_scope_poison_retains_sources_and_orphan_events(case):
    q, api = make()
    owner = Owner()
    ref = weakref.ref(owner)
    def call():
        opts = {"matched": 0 if case == "missing" else 2 if case == "extra" else 1,
                "context": 0 if case == "context" else 0x10,
                "fence": 999 if case == "fence" else 0,
                "result": 1 if case == "copy" else 0}
        api.setter(**opts)
        if case == "lookup":
            api.lookups = 0
        if case == "competing":
            api.competing = 1
        if case == "layout":
            api.copy.pitch += 1
        if case == "end":
            api.end_result = -2
    with pytest.raises(RuntimeError, match="unproven"):
        q.upload(owner, call)
    assert not api.active and api.calls[-1] == "end"
    del owner
    gc.collect()
    assert ref() is not None
    assert q.receipt()["quarantined_owners"] == 1
    assert len(q.orphans) == (0 if case == "missing" else 1)
    with pytest.raises(RuntimeError):
        q.poll()
    assert not api.released
    q.close()
    assert ref() is not None


def test_setter_exception_still_ends_scope_and_retains_orphan():
    q, api = make()
    def bad():
        api.setter()
        raise ValueError("setter failed after submission")
    with pytest.raises(RuntimeError, match="setter failed"):
        q.upload(Owner(), bad)
    assert api.calls == ["begin", "setter", "end"] and not api.active
    assert len(q.orphans) == len(q.quarantine) == 1


def test_begin_failure_skips_setter_and_end_but_retains_owner():
    q, api = make()
    api.begin_result = -5
    with pytest.raises(RuntimeError, match="begin failed"):
        q.upload(Owner(), api.setter)
    assert api.calls == ["begin"] and len(q.quarantine) == 1


@pytest.mark.parametrize("stage", ["query", "release"])
def test_event_error_poison_prevents_retries_and_keeps_all_pending(stage):
    q, api = make()
    a = q.upload(Owner(), api.setter)
    q.upload(Owner(0x456), api.setter)
    api.events[a["event"]] = 999 if stage == "query" else 0
    if stage == "release":
        api.release_result = -7  # e.g. post-destroy context restoration failed.
    with pytest.raises(RuntimeError, match="event"):
        q.poll()
    assert len(q.pending) == 2
    calls = len(api.calls)
    with pytest.raises(RuntimeError):
        q.poll()
    assert len(api.calls) == calls


def test_close_retains_pending_without_query_wait_or_release():
    q, api = make()
    owner = Owner()
    ref = weakref.ref(owner)
    q.upload(owner, api.setter)
    del owner
    calls = list(api.calls)
    q.close()
    gc.collect()
    assert ref() is not None and api.calls == calls
    assert q.receipt()["closed"] and not q.receipt()["frame_binding_proven"]
    with pytest.raises(RuntimeError, match="closed"):
        q.poll()


def test_each_frame_has_exact_owner_pointer_and_byte_pitch():
    q, api = make()
    a = q.upload(Owner(0x123), api.setter)
    b = q.upload(Owner(0x456), api.setter)
    assert a["source"] == 0x123 and b["source"] == 0x456
    assert a["width"] == a["pitch"] == 3840 and a["height"] == 600
    assert q.receipt()["peak_pending"] == 2
    assert len(q.pending) == 2
