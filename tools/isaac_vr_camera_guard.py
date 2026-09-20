"""Required feed health using source sequence and buffer metadata, never image copies."""

from __future__ import annotations

import numpy as np


class CameraGuard:
    """Camera.frame is acquisition-owned; static image content is allowed.

    Only the small frame counters cross to CPU. Checking each sensor separately
    avoids concatenating the full wrist images just to inspect their metadata.
    A reset starts a new sequence epoch; regression outside reset fails closed.
    """

    def __init__(self, max_stale_steps: int = 2) -> None:
        if max_stale_steps < 0:
            raise ValueError("camera stale tolerance must be nonnegative")
        self.max_stale_steps = max_stale_steps
        self.previous: dict[str, int] = {}
        self.stale: dict[str, int] = {}

    def reset(self) -> None:
        self.previous.clear()
        self.stale.clear()

    def sample(self, env) -> dict:
        rig = env.camera
        if hasattr(rig, "wrists"):
            sources = [
                ("left_wrist", rig.wrists[0]),
                ("right_wrist", rig.wrists[1]),
                ("demo_scene", rig.scene_camera),
            ]
        else:
            sources = [("wrists", rig)]
        roles = {}
        for role, camera in sources:
            output = camera.data.output
            pixels = output.get("rgba", output.get("rgb"))
            if hasattr(pixels, "torch"):
                pixels = pixels.torch
            channels = 4 if "rgba" in output else 3
            batch = 2 if role == "wrists" else 1
            if (
                pixels is None
                or tuple(pixels.shape) != (batch, 480, 640, channels)
                or str(pixels.dtype) not in ("torch.uint8", "uint8")
            ):
                raise RuntimeError(f"Broken required camera buffer: {role}")
            frames = camera.frame
            if hasattr(frames, "torch"):
                frames = frames.torch
            indices = frames.detach().cpu().numpy().reshape(-1)
            if len(indices) != batch or not np.isfinite(indices).all():
                raise RuntimeError(f"Broken camera sequence: {role}")
            for index, frame in enumerate(indices):
                key = f"{role}:{index}"
                frame = int(frame)
                previous = self.previous.get(key)
                if frame < 0 or (previous is not None and frame < previous):
                    raise RuntimeError(f"Camera sequence regressed without reset: {key}")
                advanced = previous is None or frame > previous
                self.stale[key] = 0 if advanced else self.stale.get(key, 0) + 1
                if self.stale[key] > self.max_stale_steps:
                    raise RuntimeError(f"Frozen required camera: {key}")
                self.previous[key] = frame
                roles[key] = {"frame_index": frame, "advanced": advanced}
        return {
            "valid": True,
            "strictly_advanced": all(v["advanced"] for v in roles.values()),
            "roles": roles,
        }
