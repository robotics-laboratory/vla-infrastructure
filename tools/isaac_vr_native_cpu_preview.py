"""Finite diagnostic CPU preview transport composed from upstream public APIs.

Call only from the existing owned-frame native callback. Each input CUDA frame
must already be producer-complete, as the existing callback guarantees using
its upstream producer-stream fence. This class does not establish that fence.
Keep the object (and therefore every immutable CPU submission) alive until
SimulationApp.close() returns, including exceptions. This deliberately bounded
probe avoids assuming undocumented ByteImageProvider host reuse completion.
No settings, RenderProducts, physics steps, or dataset frames are introduced.
"""


class CpuPreviewProbe:
    def __init__(self, providers_by_role, *, cuda_device, max_publications):
        import torch

        if max_publications < 1:
            raise ValueError("max_publications must cover warmup plus measured frames")
        self.providers = dict(providers_by_role)
        self.device = torch.device(cuda_device)
        self.stream = torch.cuda.Stream(device=self.device)
        self.done = torch.cuda.Event(enable_timing=False)
        self.staging = {}
        self.submitted = []
        self.max_publications = max_publications

    def publish_producer_complete(self, images):
        import torch

        if len(self.submitted) >= self.max_publications:
            raise RuntimeError("CPU preview probe allocation budget exhausted")
        if set(images) != set(self.providers):
            raise ValueError("Every provider must receive its corresponding owned frame")
        for role, image in images.items():
            if (image.device != self.device or image.dtype != torch.uint8
                    or image.ndim != 3 or image.shape[-1] != 4
                    or not image.is_contiguous()):
                raise ValueError("Expected producer-complete contiguous owned CUDA RGBA8")
            previous = self.staging.get(role)
            if previous is None or previous.shape != image.shape:
                self.staging[role] = torch.empty(
                    tuple(image.shape), dtype=torch.uint8, device="cpu", pin_memory=True
                )
        # All sources are retained by `images` until these D2H copies complete.
        # An explicit producer event may instead be wait_event'ed on this stream;
        # never assume torch's default stream owns a Warp/Kit producer.
        with torch.cuda.stream(self.stream):
            for role, image in images.items():
                self.staging[role].copy_(image, non_blocking=True)
            self.done.record(self.stream)
        self.done.synchronize()  # This event only; no device/context synchronization.

        # Never submit the reusable pinned staging allocation to the renderer.
        # Ordinary CPU snapshots stay alive and immutable through Kit shutdown.
        submission = {}
        for role, image in images.items():
            payload = self.staging[role].numpy().reshape(-1).copy()
            payload.flags.writeable = False
            submission[role] = payload
        self.submitted.append(submission)  # Retain before any renderer call raises.
        for role, image in images.items():
            self.providers[role].set_data_array(
                submission[role], [int(image.shape[1]), int(image.shape[0])], strict=True
            )
        # Existing caller invalidates each SceneWidget ON_DEMAND after upload.
