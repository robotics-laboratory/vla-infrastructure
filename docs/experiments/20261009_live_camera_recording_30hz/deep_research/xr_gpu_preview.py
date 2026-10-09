"""Reversible XR preview upload-only ablation; install after importing runtime.

No launch, settings changes, new RenderProducts, controller changes or encoding.
Existing partition checks, panel geometry and source-cache selection remain owned
by the project. Experimental: the CPU workaround may be needed on this Kit build.
"""

from __future__ import annotations

from time import perf_counter_ns


def install(runtime_module):
    """Change the existing CPU-staged presenter to GPU ByteImageProvider uploads.

    Call before feed binding. Restore only after feeds stop publishing. Keep the
    returned handle until teardown and save handle.receipt() with the run log.
    """
    panel_type = runtime_module._CpuRgbaPanel
    presenter_type = runtime_module._CpuStagedFeedPresenter
    before = [
        (panel_type, "upload", vars(panel_type)["upload"]),
        (presenter_type, "prepare_upload_image", vars(presenter_type)["prepare_upload_image"]),
        (presenter_type, "stage_upload_image", vars(presenter_type)["stage_upload_image"]),
    ]
    stats = dict(
        upload_calls=0,
        upload_cpu_calls=0,
        upload_cuda_calls=0,
        upload_duration_ns=0,
        staging_calls=0,
    )

    def prepare(camera_name, image, previous_source=None, previous_upload=None):
        del camera_name, previous_source, previous_upload
        # Feed images already are contiguous uint8 HWC RGBA. Retain original
        # tensor identity so this experiment introduces no extra GPU copy.
        return image

    def stage(image, upload_image):
        if image is not upload_image:
            raise RuntimeError("GPU preview ablation unexpectedly staged a copy")
        stats["staging_calls"] += 1

    def upload(self, image):
        if self._closed:
            return
        if image.device.type == "cpu":
            stats["upload_cpu_calls"] += 1
            return before[0][2](self, image)
        import torch
        from omni.gpu_foundation_factory import TextureFormat
        from omni.ui.scene import Widget

        if image.device.type != "cuda" or image.dtype != torch.uint8:
            raise TypeError("GPU preview requires CUDA uint8 RGBA")
        if image.ndim != 3 or image.shape[-1] != 4 or not image.is_contiguous():
            raise ValueError("GPU preview requires contiguous HWC RGBA")
        if min(image.shape[:2]) <= 0:
            raise ValueError("GPU preview dimensions must be positive")
        # Keep borrowed CUDA storage alive at least through the next publication,
        # matching the manager's image lifetime; producer-reuse sync is upstream.
        self._retained_image = image
        started = perf_counter_ns()
        self._upstream._provider.set_bytes_data_from_gpu(
            int(image.data_ptr()),
            [int(image.shape[1]), int(image.shape[0])],
            TextureFormat.RGBA8_UNORM,
        )
        widget = self._component.scene_widget
        if widget is not None:
            widget.update_policy = Widget.UpdatePolicy.ON_DEMAND
            widget.invalidate()
        stats["upload_duration_ns"] += perf_counter_ns() - started
        stats["upload_calls"] += 1
        stats["upload_cuda_calls"] += 1

    panel_type.upload = upload
    presenter_type.prepare_upload_image = staticmethod(prepare)
    presenter_type.stage_upload_image = staticmethod(stage)

    class Handle:
        restored = False

        def restore(self):
            if self.restored:
                return
            for owner, name, value in reversed(before):
                setattr(owner, name, value)
            self.restored = True

        def receipt(self):
            return dict(
                variant="native-gpu-preview-upload",
                experimental=True,
                headset_tested=False,
                dataset_admissible=False,
                render_products_added=0,
                source_tensor_unchanged=True,
                partition_checks_unchanged=True,
                restored=self.restored,
                **stats,
            )

    return Handle()
