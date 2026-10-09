"""OVRTX CUDA mapping -> owned Warp clone -> exact PyNv2.2.3 PacketEncoder.
No GPU at import. Instantiate after renderer init; finish BEFORE renderer teardown.
The owned queue is bounded per encoder, released by strict packet ordinal ACK plus clone fence verification.
"""

import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import threading
import time

MANIFEST = Path(__file__).with_name("isaac_vr_live_gpu_preimages.json")
_QUARANTINE = []


class _CheckedCudaFences:
    """Warp's void fence wrappers hide CUDA errors; inspect driver status here."""

    def __init__(self, *, _driver=None):
        import ctypes

        self.driver = _driver or ctypes.CDLL("libcuda.so.1")
        for name in ("cuEventSynchronize", "cuStreamSynchronize"):
            function = getattr(self.driver, name)
            function.argtypes = [ctypes.c_void_p]
            function.restype = ctypes.c_int

    def _check(self, name, handle):
        status = getattr(self.driver, name)(int(handle))
        if status != 0:
            raise RuntimeError(f"{name} failed with CUDA driver status {status}")

    def event(self, event):
        self._check("cuEventSynchronize", event.cuda_event)

    def stream(self, stream):
        self._check("cuStreamSynchronize", stream.cuda_stream)


class GPUConsumer:
    def __init__(
        self,
        directory,
        *,
        gpu=0,
        width=960,
        height=600,
        fps=30,
        adapter_path=None,
        preimage_path=None,
        capacity=8,
        _runtime=None,
    ):
        manifest = json.loads(Path(preimage_path or MANIFEST).read_text())
        for path, expected in manifest["sha256"].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"GPU consumer audited source changed: {path}")
        adapter_path = Path(
            adapter_path or Path(__file__).with_name("isaac_vr_live_nvenc.py")
        ).resolve()
        if str(adapter_path) not in manifest["sha256"]:
            raise RuntimeError("Adapter must be included in explicit source preimages")
        spec = importlib.util.spec_from_file_location("live30_pynv_adapter", adapter_path)
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        if _runtime is None:
            import warp as wp
            import ovrtx

            if (
                importlib.metadata.version("ovrtx") != "0.5.1.385782"
                or importlib.metadata.version("warp-lang") != "1.16.0"
            ):
                raise RuntimeError("Requires audited OVRTX0.5.1.385782 and Warp1.16.0")
            wp.init()
            self.device = wp.get_device(f"cuda:{gpu}")
            self.stream = wp.Stream(self.device)
            self.fences = _CheckedCudaFences()
        else:
            # Internal CPU-only fake runtime injection; never production configuration.
            wp, ovrtx, self.device, self.stream = _runtime
            self.fences = type(
                "FakeFences",
                (),
                {
                    "event": staticmethod(wp.synchronize_event),
                    "stream": staticmethod(wp.synchronize_stream),
                },
            )()
        self.wp, self.ovrtx = wp, ovrtx
        if not self.device.is_primary or not self.stream.cuda_stream:
            raise RuntimeError("Requires shared primary context and explicit non-null stream")
        self.capacity = capacity
        self.width, self.height = width, height
        self.thread = threading.get_ident()
        self.encoders, self.failed_owners = [], []
        self.closed = self.failed = False
        self.counts = [0, 0, 0]
        self.cleanup_errors = []
        try:
            with self.device.context_guard:
                for role in range(3):
                    self.encoders.append(
                        self.adapter.PacketEncoder(
                            Path(directory) / f"role{role}",
                            width=width,
                            height=height,
                            cpu=False,
                            cuda_context=self.device.context,
                            cuda_stream=self.stream.cuda_stream,
                            gpu=gpu,
                            fps=fps,
                            capacity=capacity,
                            release_owner=lambda frame: self.fences.event(frame.clone_done),
                            synchronize=lambda: self.fences.stream(self.stream),
                        )
                    )
        except BaseException:
            self.failed = True
            try:
                self.finish()
            except BaseException as cleanup:
                self.cleanup_errors.append(f"{type(cleanup).__name__}: {cleanup}")
            raise

    def __call__(self, role, render_var, *, source_id):
        if (
            self.closed
            or self.failed
            or threading.get_ident() != self.thread
            or type(role) is not int
            or role not in range(3)
        ):
            raise RuntimeError("Consumer requires healthy owner thread and camera role0..2")
        if type(source_id) is not int or source_id < 0:
            raise ValueError("Source ID must be a nonnegative exact int")
        expected_role = sum(self.counts) % 3
        expected_source = min(self.counts)
        if role != expected_role or source_id != expected_source:
            self.failed = True
            raise RuntimeError("Require one ordered role0,1,2 triplet per consecutive source ID")
        # Preflight all roles before starting a triplet; no partially submitted
        # source due merely to a known full downstream ring.
        candidates = self.encoders if role == 0 else [self.encoders[role]]
        if any(len(e.pending) >= self.capacity or e.failed or e.closed for e in candidates):
            self.failed = True
            raise RuntimeError("Triplet media capacity unavailable before mapping")
        encoder = self.encoders[role]
        if len(encoder.pending) >= self.capacity:
            raise RuntimeError("Bounded ownership queue full; no overwrite/drop permitted")
        wp, mapping, view, frame = self.wp, None, None, None
        start = time.perf_counter_ns()
        try:
            with (
                self.device.context_guard,
                wp.ScopedStream(self.stream, sync_enter=False, sync_exit=False),
            ):
                mapping = render_var.map(
                    device=self.ovrtx.Device.CUDA, sync_stream=self.stream.cuda_stream
                )
                mapped = time.perf_counter_ns()
                # OVRTX __dlpack__ IGNORES stream: map(sync_stream) above supplies the barrier.
                producer_event = mapping.wait_event
                view = wp.from_dlpack(mapping)
                if (
                    view.device != self.device
                    or view.dtype != wp.uint8
                    or tuple(view.shape) != (self.height, self.width, 4)
                    or not view.is_contiguous
                ):
                    raise ValueError("Requires primary-device contiguous HWC RGBA8 CUDA output")
                owned = wp.clone(view)
                clone_done = self.stream.record_event()
                frame = self.adapter.CudaRGBAFrame(owned, owned.ptr, self.width, self.height)
                frame.clone_done = (
                    clone_done  # retain fence and allocation together until packet ACK
                )
                del view
                view = None
                cloned = time.perf_counter_ns()
                # PyNv CopyToDeviceFrame and NVENC input/output use this same explicit stream.
                encoder.submit(frame, input_tag=int(source_id))
                submitted = time.perf_counter_ns()
                mapping.unmap(stream=self.stream.cuda_stream)
                del mapping
                mapping = None
                unmapped = time.perf_counter_ns()
            self.counts[role] += 1
            return dict(
                role=role,
                source_tag=int(source_id),
                encoder_local_ordinal=encoder.inputs - 1,
                producer_wait_event=int(producer_event) if producer_event else None,
                clone_done_event=int(clone_done.cuda_event),
                pending=len(encoder.pending),
                map_host_ms=(mapped - start) / 1e6,
                clone_enqueue_host_ms=(cloned - mapped) / 1e6,
                encode_host_ms=(submitted - cloned) / 1e6,
                unmap_host_ms=(unmapped - submitted) / 1e6,
                total_host_ms=(time.perf_counter_ns() - start) / 1e6,
                pixel_alignment_proven=False,
            )
        except BaseException as error:
            self.failed = True
            self.cleanup_errors.append(f"{type(error).__name__}: {error}")
            if frame is not None:
                self.failed_owners.append(frame)
            # Only error cleanup blocks; success path has no CPU/device-wide synchronization.
            try:
                with self.device.context_guard:
                    self.fences.stream(self.stream)
            except BaseException as cleanup:
                self.cleanup_errors.append(f"{type(cleanup).__name__}: {cleanup}")
            raise
        finally:
            if view is not None:
                del view
            if mapping is not None:
                try:
                    mapping.unmap(stream=self.stream.cuda_stream)
                except BaseException as cleanup:
                    self.failed = True
                    self.cleanup_errors.append(f"{type(cleanup).__name__}: {cleanup}")
                del mapping

    def finish(self):
        if self.closed:
            if self.failed:
                raise RuntimeError("Consumer already failed; inspect media receipt")
            return self.receipt
        if threading.get_ident() != self.thread:
            raise RuntimeError("Drain on owner thread before renderer destruction")
        errors, start = list(self.cleanup_errors), time.perf_counter_ns()
        if len(set(self.counts)) != 1:
            self.failed = True
            errors.append("Incomplete camera triplet")
        safe = False
        try:
            with self.device.context_guard:
                for encoder in self.encoders:
                    try:
                        encoder.finish()
                    except BaseException as error:
                        errors.append(f"{type(error).__name__}: {error}")
                try:
                    self.fences.stream(self.stream)
                    safe = True
                except BaseException as error:
                    errors.append(f"{type(error).__name__}: {error}")
        except BaseException as error:
            errors.append(f"{type(error).__name__}: {error}")
        finally:
            if safe:
                # PacketEncoder may have quarantined after its earlier fence
                # failed; this later successful fence now makes release safe.
                for encoder in self.encoders:
                    encoder.encoder = None
                    encoder.pending.clear()
                    encoder.input_tags.clear()
                self.failed_owners.clear()
            else:
                _QUARANTINE.append(self)
            self.closed = True
        self.failed = self.failed or bool(errors)
        self.receipt = dict(
            dataset_admissible=False,
            passed=not self.failed,
            counts=list(self.counts),
            max_pending=[e.max_pending for e in self.encoders],
            encoder_receipts=[
                getattr(
                    e,
                    "receipt",
                    {"passed": False, "drain_not_reached": True, "owners_retained": len(e.pending)},
                )
                for e in self.encoders
            ],
            drain_ms=(time.perf_counter_ns() - start) / 1e6,
            cuda_device_max_connections=os.environ.get("CUDA_DEVICE_MAX_CONNECTIONS"),
            errors=errors,
            owners_quarantined=not safe,
            synchronization="producer wait -> owned clone -> same-stream NVENC; strict packet ACK plus clone fence; drain fence before failure release",
            pixel_alignment_proven=False,
        )
        if self.failed:
            raise RuntimeError("; ".join(errors) or "Consumer failed earlier")
        return self.receipt


def write_preimages(destination, reference=None):
    """Generate local guards while refusing changed audited installed SDK bytes."""
    tools = Path(__file__).resolve().parent
    helpers = tools.parent / "docs/experiments/20261009_live_camera_recording_30hz/deep_research"
    reference = Path(reference or helpers / "ovrtx_gpu_consumer_preimages.json")
    audited = json.loads(reference.read_text())
    guarded = {p: sha for p, sha in audited["sha256"].items() if p != audited["adapter"]}
    for path, expected in guarded.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Changed audited installed source: {path}")
    for path in [
        tools / "isaac_vr_live_nvenc.py",
        tools / "isaac_vr_live_gpu.py",
        tools / "isaac_vr_live_worker.py",
        helpers / "ovrtx_snapshot.py",
        helpers / "optical_witness.py",
    ]:
        guarded[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dict(
        schema="isaac_vr_live_gpu_preimages_v1",
        adapter=str(tools / "isaac_vr_live_nvenc.py"),
        sha256=guarded,
        reference=str(reference),
        gpu_run=False,
    )
    Path(destination).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def has_quarantined_owners():
    """Constructor errors can quarantine a consumer before caller receives it."""
    return bool(_QUARANTINE)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate checked live-media source guards; no GPU import"
    )
    parser.add_argument("--write-preimages", required=True)
    parser.add_argument("--reference")
    args = parser.parse_args()
    write_preimages(args.write_preimages, args.reference)
