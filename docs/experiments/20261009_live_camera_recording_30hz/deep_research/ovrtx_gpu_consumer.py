"""OVRTX CUDA mapping -> owned Warp clone -> exact PyNv2.2.3 PacketEncoder.
No GPU at import. Instantiate after renderer init; finish BEFORE renderer teardown.
The owned queue is bounded per encoder, released only by packet-ordinal ACK.
"""

import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import threading
import time

MANIFEST = Path(__file__).with_name("ovrtx_gpu_consumer_preimages.json")


class GPUConsumer:
    def __init__(self, directory, *, gpu=0, width=960, height=600, fps=30):
        manifest = json.loads(MANIFEST.read_text())
        for path, expected in manifest["sha256"].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"GPU consumer audited source changed: {path}")
        spec = importlib.util.spec_from_file_location("live30_pynv_adapter", manifest["adapter"])
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        import warp as wp
        import ovrtx

        if (
            importlib.metadata.version("ovrtx") != "0.5.1.385782"
            or importlib.metadata.version("warp-lang") != "1.16.0"
        ):
            raise RuntimeError("Requires audited OVRTX0.5.1.385782 and Warp1.16.0")
        self.wp, self.ovrtx = wp, ovrtx
        wp.init()
        self.device = wp.get_device(f"cuda:{gpu}")
        if not self.device.is_primary:
            raise RuntimeError("Requires CUDA primary context shared with OVRTX/NVENC")
        self.stream = wp.Stream(self.device)
        if not self.stream.cuda_stream:
            raise RuntimeError("Explicit non-null stream required; PyNv replaces stream0")
        self.width, self.height = width, height
        self.thread = threading.get_ident()
        self.encoders, self.failed_owners = [], []
        self.closed = self.failed = False
        self.counts = [0, 0, 0]
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
                        )
                    )
        except BaseException:
            self.finish()
            raise

    def __call__(self, role, render_var, *, source_id):
        if (
            self.closed
            or self.failed
            or threading.get_ident() != self.thread
            or role not in range(3)
        ):
            raise RuntimeError("Consumer requires healthy owner thread and camera role0..2")
        encoder = self.encoders[role]
        if len(encoder.pending) >= 8:
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
        except BaseException:
            self.failed = True
            if frame is not None:
                self.failed_owners.append(frame)
            # Only error cleanup blocks; success path has no CPU/device-wide synchronization.
            with self.device.context_guard:
                wp.synchronize_stream(self.stream)
            raise
        finally:
            if view is not None:
                del view
            if mapping is not None:
                mapping.unmap(stream=self.stream.cuda_stream)
                del mapping

    def finish(self):
        if self.closed:
            return
        if threading.get_ident() != self.thread:
            raise RuntimeError("Drain on owner thread before renderer destruction")
        held = self.failed_owners + [f for e in self.encoders for f in e.pending.values()]
        errors, start = [], time.perf_counter_ns()
        with self.device.context_guard:
            try:
                for encoder in self.encoders:
                    if not encoder.closed:
                        try:
                            encoder.finish()
                        except BaseException as error:
                            errors.append(f"{type(error).__name__}: {error}")
            finally:
                # Drain/error boundary only: protect retained owners even if EndEncode raises.
                self.wp.synchronize_stream(self.stream)
                held.clear()
                self.failed_owners.clear()
                self.closed = True
        self.receipt = dict(
            dataset_admissible=False,
            counts=self.counts,
            max_pending=[e.max_pending for e in self.encoders],
            drain_ms=(time.perf_counter_ns() - start) / 1e6,
            cuda_device_max_connections=os.environ.get("CUDA_DEVICE_MAX_CONNECTIONS"),
            errors=errors,
            synchronization="OVRTX map producer-event wait -> clone -> NVENC copy/encode on one stream; packet ordinal ACK owns lifetime",
            pixel_alignment_proven=False,
        )
        if errors:
            raise RuntimeError("; ".join(errors))
        return self.receipt
