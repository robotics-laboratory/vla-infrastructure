"""Opt-in host timings around existing native recording calls; no extra GPU work.

Inclusive durations can overlap: callback copies occur inside the ordinary Kit
pump, and snapshot sampling occurs inside canonical observation capture. CUDA
durations measure host calls and waits, not GPU execution time.
"""

from __future__ import annotations

import cProfile
import json
from pathlib import Path
import statistics
import threading
import time


class _Proxy:
    def __init__(self, original, overrides):
        self._original, self._overrides = original, overrides

    def __getattr__(self, name):
        return self._overrides[name] if name in self._overrides else getattr(self._original, name)


class NativeProfile:
    """Install after media setup; leave before media/record lifecycle teardown."""

    def __init__(self, *, env, performance_logger, record, media, output, cprofile=False, nvtx=False):
        self.env, self.performance_logger, self.record, self.media = env, performance_logger, record, media
        self.output = Path(output)
        self.profiler = cProfile.Profile() if cprofile else None
        self.nvtx = None
        if nvtx:
            import torch
            self.nvtx = torch.cuda.nvtx
        self.rows, self.restores = [], []
        self.thread = threading.get_ident()
        self.entered = self.closed = False

    def _timed(self, name, previous):
        def call(*args, **kwargs):
            if self.nvtx is not None:
                self.nvtx.range_push(name)
            begin = time.monotonic_ns()
            success = False
            try:
                result = previous(*args, **kwargs)
                success = True
                return result
            finally:
                end = time.monotonic_ns()
                self.rows.append(dict(stage=name, begin_monotonic_ns=begin,
                                      end_monotonic_ns=end, duration_ns=end-begin,
                                      succeeded=success, thread_id=threading.get_ident()))
                if self.nvtx is not None:
                    self.nvtx.range_pop()
        return call

    def _replace(self, target, name, value):
        namespace = vars(target)
        self.restores.append((target, name, name in namespace, namespace.get(name), value))
        setattr(target, name, value)

    def _wrap(self, target, name, stage):
        self._replace(target, name, self._timed(stage, getattr(target, name)))

    def __enter__(self):
        if self.entered or self.closed or threading.get_ident() != self.thread:
            raise RuntimeError("Native profile requires one owner-thread scope")
        self.entered = True
        try:
            self._replace(self.env, "performance_logger", self.performance_logger)
            self._wrap(self.record.sampler, "capture_frame", "snapshot_recordables")
            if self.media is not None:
                self._wrap(self.media, "previous", "canonical_observation")
                self._wrap(self.media, "_pump", "held_camera_pump")
                source = getattr(self.media, "source_proof", None)
                if source is not None:
                    self._wrap(source, "_publish", "native_source_publication")
                    self._wrap(source, "_sync_to_fabric", "added_usd_fabric_sync")
                    self._wrap(source, "observe", "rendered_source_comparison")
                consumer = getattr(self.media, "consumer", None)
                if consumer is not None:
                    self._wrap(consumer, "_receive", "native_result_callback")
                for role, encoder in enumerate(self.media.encoders):
                    self._wrap(encoder, "submit", f"encoder_submit_role{role}")
                if self.media.preview is not None:
                    self._wrap(self.media.preview, "publish", "preview_publish")
                self._wrap(self.media.fences, "stream", "encoder_stream_fence")
                original_torch = self.media.torch
                cuda = _Proxy(original_torch.cuda, {
                    "synchronize": self._timed("media_cuda_synchronize", original_torch.cuda.synchronize)
                })
                self._replace(self.media, "torch", _Proxy(original_torch, {"cuda": cuda}))
            if self.profiler is not None:
                self.profiler.enable()
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        if threading.get_ident() != self.thread:
            raise RuntimeError("Native profile must close on its owner thread")
        if self.profiler is not None:
            self.profiler.disable()
        errors = []
        for target, name, owned, previous, installed in reversed(self.restores):
            if vars(target).get(name) is not installed:
                errors.append(f"Observer ownership changed: {name}")
                continue
            if owned:
                setattr(target, name, previous)
            else:
                vars(target).pop(name, None)
        self.restores.clear()
        self.closed = True
        self.output.parent.mkdir(parents=True, exist_ok=True)
        profile_path = None
        if self.profiler is not None:
            profile_path = self.output.with_suffix(".prof")
            self.profiler.dump_stats(str(profile_path))
        stages = {}
        for name in sorted({row["stage"] for row in self.rows}):
            values = sorted(row["duration_ns"] / 1e6 for row in self.rows if row["stage"] == name)
            stages[name] = dict(count=len(values), mean_ms=statistics.fmean(values),
                                max_ms=max(values), total_ms=sum(values))
        self.output.write_text(json.dumps(dict(
            schema="native_recording_host_profile_v1", stages=stages, rows=self.rows,
            restore_errors=errors, cprofile=str(profile_path) if profile_path else None,
            timing_semantics="Inclusive host durations and existing waits; stages overlap; no GPU timing claim",
            extra_gpu_work=False, action_mutation=False, dataset_admissible=False,
        ), indent=2) + "\n")
        if errors:
            raise RuntimeError("Native profile cleanup failed: " + str(errors))

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
