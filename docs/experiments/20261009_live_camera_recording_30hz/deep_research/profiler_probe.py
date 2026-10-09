"""Opt-in NVTX stage observer for initialized Piper/Isaac experiment only.

No synchronization, tensor inspection, render pump, or SDK byte mutation.
Install AFTER all experimental wrappers; restore BEFORE their restoration.
nsys: --capture-range=nvtx --nvtx-capture=live30_capture --capture-range-end=stop.
This measures execution; it does not validate camera/source alignment.
"""

from contextlib import contextmanager
import functools
import hashlib
import os
from pathlib import Path
import threading


class Observer:
    def __init__(self, env, logger, *, warmup=30, frames=120, ik=None):
        if warmup < 0 or frames < 1:
            raise ValueError("Invalid profiler window")
        import torch.cuda.nvtx as nvtx

        self.nvtx = nvtx
        self.changes = []
        self.owner_thread = threading.get_ident()
        self.tick = 0
        self.capture_open = False
        self.control_open = False
        self.counts = {}
        self.warmup, self.frames = warmup, frames
        try:
            self._replace(logger, "begin_step", self._begin(logger.begin_step))
            self._replace(logger, "end_step", self._end(logger.end_step))
            original_stage = logger.stage

            @contextmanager
            def stage(name):
                with self.zone("stage:" + name), original_stage(name):
                    yield

            self._replace(logger, "stage", stage)
            self.wrap(env, "_advance", "advance_and_packets")
            self.wrap(env, "capture_measured_state", "state_D2H")
            self.wrap(env, "_apply", "native_target_mapping")
            self.wrap(
                env.sim, "step", lambda *a, **kw: "sim_step:render=" + str(kw.get("render", True))
            )
            self.wrap(env.sim, "render", "sim_render")
            for index, robot in enumerate(env.robots):
                self.wrap(robot, "write_data_to_sim", f"robot{index}:write")
                self.wrap(robot, "update", f"robot{index}:update")
            self.wrap(env.camera, "update", "camera_update")
            if hasattr(env.camera, "capture_boundary"):
                self.wrap(env.camera, "capture_boundary", "camera_boundary")
            if getattr(env, "vr_runtime", None) is not None:
                self.wrap(env.vr_runtime, "update", "vr_runtime_update")
            if ik is not None:
                self.wrap(ik, "solve", "ik_solve")
        except BaseException:
            self.restore()
            raise

    @contextmanager
    def zone(self, name):
        # Python scopes may run outside the measured range. No GPU dependency added.
        self.counts[name] = self.counts.get(name, 0) + 1
        self.nvtx.range_push(name)
        try:
            yield
        finally:
            self.nvtx.range_pop()

    def _replace(self, obj, name, value):
        previous = vars(obj).get(name)
        existed = name in vars(obj)
        setattr(obj, name, value)
        self.changes.append((obj, name, existed, previous))

    def wrap(self, obj, name, label):
        original = getattr(obj, name)

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            name = label(*args, **kwargs) if callable(label) else label
            with self.zone(name):
                return original(*args, **kwargs)

        self._replace(obj, name, wrapped)

    def _begin(self, original):
        @functools.wraps(original)
        def begin(*args, **kwargs):
            if threading.get_ident() != self.owner_thread or self.control_open:
                raise RuntimeError("Profiler expected serial paired control boundaries")
            self.tick += 1
            if self.tick == self.warmup + 1:
                self.nvtx.range_push("live30_capture")
                self.capture_open = True
            if self.capture_open:
                self.nvtx.range_push(f"control:{self.tick}")
                self.control_open = True
            return original(*args, **kwargs)

        return begin

    def _end(self, original):
        @functools.wraps(original)
        def end(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                if self.control_open:
                    self.nvtx.range_pop()
                    self.control_open = False
                if self.capture_open and self.tick == self.warmup + self.frames:
                    self.nvtx.range_pop()
                    self.capture_open = False

        return end

    def receipt(self):
        return {
            "observer_only": True,
            "tensor_reads_added": False,
            "synchronization_added": False,
            "source_alignment_proven": False,
            "warmup": self.warmup,
            "frames": self.frames,
            "begun_ticks": self.tick,
            "method_counts": dict(self.counts),
            "thread_id": self.owner_thread,
            "cpu_affinity": sorted(os.sched_getaffinity(0)),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }

    def restore(self):
        if self.control_open:
            self.nvtx.range_pop()
            self.control_open = False
        if self.capture_open:
            self.nvtx.range_pop()
            self.capture_open = False
        for obj, name, existed, previous in reversed(self.changes):
            if existed:
                setattr(obj, name, previous)
            else:
                delattr(obj, name)
        self.changes.clear()


def install(env, logger, *, warmup=30, frames=120, ik=None):
    return Observer(env, logger, warmup=warmup, frames=frames, ik=ik)
