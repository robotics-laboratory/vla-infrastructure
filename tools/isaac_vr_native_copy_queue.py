"""Experimental scoped CUDA preview completion; no wait, no UI/frame-binding claim.

Keep this queue strongly owned until SimulationApp.close returns. close() stops
submissions and preserves every pending/quarantined owner and orphan event.
Source production must already be ordered before the SDK provider copy. The
source is immutable until acknowledgement; this queue does not order producers.
"""
from __future__ import annotations

import ctypes
import threading
from collections import deque
from dataclasses import dataclass


class CopyReceipt(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("event", "context", "source", "width", "height", "pitch")] + [
                    (name, ctypes.c_int) for name in
                    ("matched_calls", "copy_result", "fence_status")]

    def scalars(self):
        return {name: int(getattr(self, name)) for name, _ in self._fields_}


@dataclass
class Borrow:
    owner: object
    copy: CopyReceipt


class ProviderCopyQueue:
    """Main-thread-only bounded borrow queue; errors permanently poison it."""
    def __init__(self, *, max_pending=12, shim_path=None, api=None):
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self._api = api if api is not None else ctypes.CDLL(shim_path or None)
        if api is None:
            specs = {
                "begin": ([ctypes.c_uint64] * 4, ctypes.c_int),
                "end": ([ctypes.POINTER(CopyReceipt)], ctypes.c_int),
                "query": ([ctypes.c_uint64] * 2, ctypes.c_int),
                "release": ([ctypes.c_uint64] * 2, ctypes.c_int),
                "intercepted_lookups": ([], ctypes.c_uint64),
                "competing_bindings": ([], ctypes.c_uint64),
                "receipt_size": ([], ctypes.c_uint64),
            }
            for name, (args, result) in specs.items():
                fn = getattr(self._api, "vla_copy_probe_" + name)
                fn.argtypes, fn.restype = args, result
        self._thread = threading.get_ident()
        self.max_pending = int(max_pending)
        self.pending = {}  # Public to make retained ownership inspectable.
        self.quarantine = []
        self.orphans = []  # Events from failed scopes: never query/destroy again.
        self._active_owner = None
        self._busy = False
        self._closed = False
        self._poison = None
        self._submitted = self._released = self._peak = self._attempted = 0
        self._history = deque(maxlen=64)
        if self._fn("receipt_size")() != ctypes.sizeof(CopyReceipt):
            self._fail("shim receipt ABI size mismatch")

    def _fn(self, name):
        return getattr(self._api, "vla_copy_probe_" + name)

    def _fail(self, message):
        if self._poison is None:
            self._poison = str(message)
        raise RuntimeError(self._poison)

    def _ready(self):
        if threading.get_ident() != self._thread:
            self._fail("queue thread changed; scope uses thread-local state")
        if self._closed:
            raise RuntimeError("queue closed; retained owners remain anchored")
        if self._poison is not None:
            raise RuntimeError(self._poison)
        if self._busy:
            self._fail("reentrant queue operation")

    @staticmethod
    def _layout(owner):
        shape = tuple(owner.shape)
        if (str(owner.dtype) != "torch.uint8" or owner.device.type != "cuda"
                or len(shape) != 3 or shape[2] != 4 or min(shape) <= 0
                or not owner.is_contiguous()):
            raise ValueError("source must be contiguous CUDA uint8 HWC RGBA")
        # Positive contiguous uint8 HWC has a packed row pitch; no SDK ABI cast.
        return int(owner.data_ptr()), int(shape[1]) * 4, int(shape[0]), int(shape[1]) * 4

    def upload(self, owner, call):
        """Call the actual setter once inside a source-specific capture scope."""
        self._ready()
        # Caller should poll once at the next iteration before its triplet.
        # Do not wait or submit another borrowed source after budget exhaustion.
        if len(self.pending) >= self.max_pending:
            self._fail("pending source/event budget exhausted before begin")
        try:
            layout = self._layout(owner)
        except Exception as exc:
            self._fail(f"source layout error: {exc}")
        if self._fn("competing_bindings")():
            self._fail("competing CUDA runtime lookup binding")
        self._attempted += 1
        self._active_owner = owner  # Retain BEFORE the setter can borrow it.
        self._busy = True
        captured = CopyReceipt()
        started = False
        error = None
        begin_status = end_status = None
        try:
            begin_status = self._fn("begin")(*layout)
            if begin_status != 0:
                raise RuntimeError(f"scope begin failed: {begin_status}")
            started = True
            call()
        except BaseException as exc:
            error = exc
        finally:
            try:
                if started:
                    end_status = self._fn("end")(ctypes.byref(captured))
            except BaseException as exc:
                if error is None:
                    error = exc
            finally:
                self._busy = False
        record = captured.scalars()
        record.update(begin_status=begin_status, end_status=end_status)
        self._history.append(record)
        valid = (error is None and end_status == 0 and captured.matched_calls == 1
                 and captured.copy_result == 0 and captured.fence_status == 0
                 and captured.event != 0 and captured.context != 0
                 and tuple(getattr(captured, k) for k in
                           ("source", "width", "height", "pitch")) == layout
                 and captured.event not in self.pending)
        try:
            valid = (valid and self._fn("intercepted_lookups")() > 0
                     and self._fn("competing_bindings")() == 0)
        except BaseException as exc:
            valid = False
            if error is None:
                error = exc
        if not valid:
            self.quarantine.append(owner)
            if captured.event:
                self.orphans.append(Borrow(owner, captured))
            self._active_owner = None
            reason = f"copy scope unproven: {record}"
            if error is not None:
                reason += f"; call/end error: {error!r}"
            self._fail(reason)
        self.pending[int(captured.event)] = Borrow(owner, captured)
        self._active_owner = None
        self._submitted += 1
        self._peak = max(self._peak, len(self.pending))
        return record

    def poll(self):
        """Only cuEventQuery; release source after query AND event release succeed."""
        self._ready()
        released = 0
        for event, borrow in tuple(self.pending.items()):
            try:
                status = self._fn("query")(event, borrow.copy.context)
                if status == 600:  # Published CUDA_ERROR_NOT_READY.
                    continue
                if status != 0:
                    self._fail(f"event/context query failed: {status}")
                status = self._fn("release")(event, borrow.copy.context)
                if status != 0:
                    self._fail(f"event/context release failed: {status}")
            except BaseException as exc:
                # Keep all remaining owners, even if driver destroy succeeded
                # and a later context-pop failed. No retries after poisoning.
                self._fail(f"event operation failed: {exc!r}")
            del self.pending[event]
            self._released += 1
            released += 1
        return released

    def receipt(self):
        return {"experimental": True, "submitted": self._submitted,
                "attempted": self._attempted, "released": self._released,
                "pending": len(self.pending), "peak_pending": self._peak,
                "max_pending": self.max_pending,
                "quarantined_owners": len(self.quarantine),
                "orphan_events": len(self.orphans), "closed": self._closed,
                "poison": self._poison, "recent_scopes": list(self._history),
                "retained_until_app_close": True,
                "frame_binding_proven": False}

    def close(self):
        """Stop operations; preserve pending sources/events until app teardown."""
        self._closed = True
        return self.receipt()
