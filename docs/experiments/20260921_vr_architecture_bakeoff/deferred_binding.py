"""One-deep, experiment-only deferred observation binding.

This module deliberately does not acquire cameras, render, advance physics, or
write a dataset.  A content-sensitive experiment supplies the observed source
identity.  The binder only enforces the known one-control-depth transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

import numpy as np


ROLES = ("left_wrist", "right_wrist", "scene")


class DeferredBindingViolation(RuntimeError):
    """The pending observation cannot be published without guessing."""


@dataclass(frozen=True)
class RenderSourceIdentity:
    obs_id: int
    control_tick_id: int
    reset_epoch: int
    reference_epoch: int
    session_epoch: int
    state_generation: int
    physics_step: int
    render_request_generation: int


@dataclass(frozen=True)
class PendingObservation:
    source: RenderSourceIdentity
    state: tuple[float, ...]
    state_sha256: str
    images_pending: bool = True


@dataclass(frozen=True)
class CameraExtractionIdentity:
    role: str
    frame: int
    data_generation: int
    extraction_id: int


@dataclass(frozen=True)
class DeferredImages:
    source: RenderSourceIdentity
    availability_control_tick: int
    availability_render_generation: int
    cameras: tuple[CameraExtractionIdentity, ...]
    rgb_sha256: tuple[str, ...]


@dataclass(frozen=True)
class ObservationSnapshot:
    source: RenderSourceIdentity
    state: tuple[float, ...]
    state_sha256: str
    images: DeferredImages
    rgb: tuple[np.ndarray, ...]


def _state_bytes(state: tuple[float, ...]) -> bytes:
    return b"state:<f4:[14]:deg/mm:" + np.asarray(state, dtype="<f4").tobytes()


class OneTickDeferredBinder:
    """Fail-closed binder for exactly one pending three-camera observation."""

    def __init__(self) -> None:
        self.pending: PendingObservation | None = None
        self.latest: ObservationSnapshot | None = None
        self.invalidations: list[str] = []
        self._camera_sequences: dict[str, tuple[int, int, int]] = {}
        self._published_obs_ids: set[int] = set()
        self._render_requests: set[int] = set()

    def prepare(self, source: RenderSourceIdentity, state: tuple[float, ...]) -> PendingObservation:
        if self.pending is not None:
            raise DeferredBindingViolation("pending_observation_exists")
        if len(state) != 14 or not np.isfinite(state).all():
            raise DeferredBindingViolation("invalid_state_payload")
        if source.obs_id in self._published_obs_ids:
            raise DeferredBindingViolation("duplicate_observation_identity")
        if source.render_request_generation in self._render_requests:
            raise DeferredBindingViolation("duplicate_render_request_identity")
        payload = _state_bytes(state)
        pending = PendingObservation(source, tuple(float(v) for v in state), sha256(payload).hexdigest())
        self.pending = pending
        self._render_requests.add(source.render_request_generation)
        return pending

    def abort(self, reason: str) -> None:
        if not reason:
            raise ValueError("abort reason is required")
        self.pending = None
        self.invalidations.append(reason)

    def invalidate_epoch(self, reason: str) -> None:
        """Abort pending work and restart epoch-local camera identity floors."""
        self.abort(reason)
        self._camera_sequences.clear()

    def complete(
        self,
        *,
        observed_source: RenderSourceIdentity,
        availability_control_tick: int,
        availability_render_generation: int,
        camera_identities: tuple[CameraExtractionIdentity, ...],
        rgb: Mapping[str, np.ndarray],
        drain: bool = False,
    ) -> ObservationSnapshot:
        pending = self.pending
        if pending is None:
            raise DeferredBindingViolation("no_pending_observation")
        if observed_source != pending.source:
            raise DeferredBindingViolation("unexpected_image_source")
        expected_tick = pending.source.control_tick_id if drain else pending.source.control_tick_id + 1
        if availability_control_tick != expected_tick:
            raise DeferredBindingViolation("availability_tick_mismatch")
        if availability_render_generation != pending.source.render_request_generation + 1:
            raise DeferredBindingViolation("render_generation_slip")
        roles = tuple(identity.role for identity in camera_identities)
        if roles != ROLES or tuple(rgb) != ROLES:
            raise DeferredBindingViolation("incomplete_or_reordered_camera_bundle")
        if len({identity.extraction_id for identity in camera_identities}) != 1:
            raise DeferredBindingViolation("camera_extraction_disagreement")
        frozen = []
        digests = []
        for identity in camera_identities:
            previous = self._camera_sequences.get(identity.role)
            current = (identity.frame, identity.data_generation, identity.extraction_id)
            if previous is not None and any(now <= old for now, old in zip(current, previous, strict=True)):
                raise DeferredBindingViolation(f"{identity.role}:duplicate_or_stale_camera_identity")
            image = np.asarray(rgb[identity.role])
            if image.shape != (480, 640, 3) or image.dtype != np.uint8 or not image.flags.owndata:
                raise DeferredBindingViolation(f"{identity.role}:invalid_rgb_payload")
            image.setflags(write=False)
            frozen.append(image)
            digests.append(sha256(image.tobytes()).hexdigest())
        images = DeferredImages(
            observed_source,
            availability_control_tick,
            availability_render_generation,
            camera_identities,
            tuple(digests),
        )
        snapshot = ObservationSnapshot(
            pending.source,
            pending.state,
            pending.state_sha256,
            images,
            tuple(frozen),
        )
        self.pending = None
        self.latest = snapshot
        self._published_obs_ids.add(snapshot.source.obs_id)
        self._camera_sequences.update(
            (identity.role, (identity.frame, identity.data_generation, identity.extraction_id))
            for identity in camera_identities
        )
        return snapshot
