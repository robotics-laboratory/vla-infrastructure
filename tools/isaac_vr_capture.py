"""One current three-camera boundary; no rendering, episode storage, or recorder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

ROLES = ("left_wrist", "right_wrist", "scene")


@dataclass(frozen=True)
class ProducerBoundary:
    reset_epoch: int
    physics_step: int
    render_generation: int


@dataclass(frozen=True)
class CameraIdentity:
    role: str
    frame: int
    data_generation: int


@dataclass(frozen=True)
class ObservationCapture:
    producer: ProducerBoundary
    capture_cycle: int
    cameras: tuple[CameraIdentity, ...]
    state: tuple[float, ...]
    eligible: bool


def tensor(value: Any) -> Any:
    return getattr(value, "torch", value)


def frame(camera: Any) -> int:
    return int(tensor(camera.frame).reshape(-1)[0].item())


class ThreeCameraCapture:
    """Qualify synchronous upstream extraction, then lend only its current boundary.

    SensorBase's completed data generation is checked before accessing ``data``:
    consumers must never trigger its lazy camera update. Buffers stay upstream-owned;
    only ``freeze`` requests three CPU RGB copies. Callers serialize physics/reset
    and capture/consumption on the simulation thread.
    """

    def __init__(
        self,
        cameras: dict[str, Any],
        boundary: Callable[[], ProducerBoundary],
        read_state: Callable[[], tuple[int, tuple[float, ...]]],
    ) -> None:
        if tuple(cameras) != ROLES:
            raise ValueError("Expected ordered left_wrist, right_wrist, scene")
        self.cameras = cameras
        self.boundary = boundary
        self.read_state = read_state
        self.successful_capture_cycle = 0
        self.failed_attempts = 0
        self.last_error: str | None = None
        self._latest: ObservationCapture | None = None
        self._buffers: dict[str, Any] = {}

    def invalidate(self) -> None:
        self._latest = None
        self._buffers.clear()

    @staticmethod
    def _output(camera: Any) -> Any:
        # Pinned SensorBase sets this receipt only AFTER extraction returns.
        if camera._data_generation_last_update != camera._data_generation:
            raise RuntimeError("Camera output has no completed producer generation")
        output = camera.data.output
        value = output.get("rgba", output.get("rgb"))
        if value is None or tuple(value.shape) not in ((1, 480, 640, 3), (1, 480, 640, 4)):
            raise RuntimeError("Camera output missing or wrong shape")
        if str(tensor(value).dtype).split(".")[-1] != "uint8":
            raise RuntimeError("Camera output must be uint8")
        return value

    def capture(self, dt: float, *, eligible: bool = True) -> ObservationCapture | None:
        self.invalidate()
        try:
            producer = self.boundary()
            state_step, state = self.read_state()
            if state_step != producer.physics_step or self.boundary() != producer:
                raise RuntimeError("Measured state does not belong to capture boundary")
            if len(state) != 14 or not np.isfinite(state).all():
                raise RuntimeError("Invalid measured state")
            identities = []
            buffers = {}
            for role, camera in self.cameras.items():
                previous_frame, generation = frame(camera), camera._data_generation
                camera.update(dt, force_recompute=True)
                if frame(camera) != previous_frame + 1 or camera._data_generation <= generation:
                    raise RuntimeError(f"{role}: camera producer did not advance exactly once")
                buffers[role] = self._output(camera)
                identities.append(CameraIdentity(role, frame(camera), camera._data_generation))
            if self.boundary() != producer:
                raise RuntimeError("Producer changed during three-camera extraction")
            self._buffers = buffers
            candidate = ObservationCapture(
                producer, self.successful_capture_cycle + 1, tuple(identities), state, eligible
            )
            self._check_current(candidate)
            self._latest = candidate
            self.successful_capture_cycle += 1
            self.last_error = None
            return candidate
        except Exception as error:  # Reject the bundle; RUN policy belongs to its caller.
            self.invalidate()
            self.failed_attempts += 1
            self.last_error = str(error)
            return None

    def _check_current(self, capture: ObservationCapture) -> None:
        if self.boundary() != capture.producer:
            raise RuntimeError("Capture is no longer at the current producer boundary")
        for identity in capture.cameras:
            camera = self.cameras[identity.role]
            if frame(camera) != identity.frame or camera._data_generation != identity.data_generation:
                raise RuntimeError("Camera source identity changed after capture")
            if self._output(camera) is not self._buffers[identity.role]:
                raise RuntimeError("Camera buffer replaced after capture")
        if self.boundary() != capture.producer:
            raise RuntimeError("Producer changed while reading current capture")

    def latest(self, *, require_eligible: bool = True) -> ObservationCapture:
        if self._latest is None:
            raise RuntimeError(self.last_error or "No successful observation capture")
        self._check_current(self._latest)
        if require_eligible and not self._latest.eligible:
            raise RuntimeError("Startup settling is not an eligible observation")
        return self._latest

    def freeze(self) -> dict[str, np.ndarray]:
        """Optional owned CPU snapshot; no physics, camera update, or render call."""
        capture = self.latest()
        result = {"observation.state": np.asarray(capture.state, dtype=np.float32)}
        for role, buffer in self._buffers.items():
            rgb = tensor(buffer)[0, ..., :3]
            if hasattr(rgb, "detach"):
                rgb = rgb.detach().cpu().numpy()
            result[f"observation.images.{role}"] = np.array(rgb, dtype=np.uint8, copy=True)
        self._check_current(capture)
        return result
