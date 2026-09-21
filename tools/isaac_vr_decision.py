"""In-memory Isaac human decision receipts; no acquisition clock or storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

import numpy as np

from tools.d0_causal import CausalTransactionValidator, Epoch, PayloadIdentity, SourceIdentity
from tools.isaac_vr_capture import ObservationCapture

DECISION_REVISION = "piper_x_xr_preclip_decision_v1"


def payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class ResolvedXrInput:
    session_epoch: int
    control_reference_epoch: int
    deviceio_update_epoch: int
    submitted_frame_id: int
    returned_frame_id: int
    ran_synchronously: bool
    hands: tuple  # per-hand None or ordered (ControllerInputIndex.name, owned value) pairs
    world_transform: tuple[float, ...]
    rebased: bool
    tracking_valid: tuple[bool, bool]


class XrInputReceipt:
    """One source receipt. Poll is reached only after upstream DeviceIO.update returns."""

    def __init__(self) -> None:
        self.session: Any = None
        self.session_epoch = 0
        self.reference_epoch = 0
        self.update_epoch = 0
        self.frame = -1
        self.hands: tuple | None = None
        self.transform: tuple[float, ...] = ()
        self.rebased = False
        self.tracking_valid = (False, False)
        self.last_consumed = 0
        self.session_provider: Any = None

    def polled(self, session: Any, frame: int) -> None:
        if session is not self.session:
            self.session = session
            self.session_epoch += 1
            self.reference_epoch += 1
        self.update_epoch += 1
        self.frame = frame
        self.hands = None

    def transformed(self, hands: tuple, matrix: Any, reset: bool, tracking=(True, True)) -> None:
        transform = tuple(float(v) for v in np.from_dlpack(matrix).reshape(-1))
        if reset or transform != self.transform or tracking != self.tracking_valid:
            self.reference_epoch += 1
        self.transform, self.hands, self.rebased = transform, hands, reset
        self.tracking_valid = tracking

    def resolve(self, info: Any, previous_update: int) -> ResolvedXrInput:
        if (self.update_epoch != previous_update + 1 or self.hands is None
                or not info.ran_synchronously or info.worker_exception is not None
                or info.submitted_frame_id != self.frame or info.returned_frame_id != self.frame):
            raise RuntimeError("XR update/request/result mismatch")
        return ResolvedXrInput(
            self.session_epoch, self.reference_epoch, self.update_epoch, self.frame, self.frame,
            True, self.hands, self.transform, self.rebased, self.tracking_valid,
        )

    def validate(self, xr: ResolvedXrInput) -> None:
        if (xr.session_epoch != self.session_epoch
                or xr.control_reference_epoch != self.reference_epoch
                or xr.deviceio_update_epoch != self.update_epoch
                or xr.deviceio_update_epoch <= self.last_consumed):
            raise RuntimeError("XR session/reference/update changed or reused")


def check_observation(env: Any, observation: ObservationCapture | None) -> None:
    if observation is not None:
        if (env.latest_observation_capture() is not observation
                or env._state_physics_step != observation.producer.physics_step
                or env.sim.get_physics_step_count() != observation.producer.physics_step):
            raise RuntimeError("IK observation/state generation mismatch")


@dataclass(frozen=True)
class SolvedControlDecision:
    control_tick_id: int | None  # None for ordinary RUN holds outside D0 admission.
    observation_identity: ObservationCapture | None
    xr_identity: ResolvedXrInput | None
    cartesian_intent: Any  # frozen BimanualTeleopCommand includes processor identity
    native_preclip: tuple[float, ...]
    native_clipped: tuple[float, ...]
    canonical_d0_action: bytes  # exactly little-endian float32[14], immutable

    @property
    def processor_identity(self) -> tuple[str, str, int]:
        command = self.cartesian_intent
        return command.processor_revision, command.provenance_revision, command.processor_generation

    @property
    def dataset_action(self) -> np.ndarray:
        return np.frombuffer(self.canonical_d0_action, dtype="<f4")

    @property
    def residual(self) -> tuple[float, ...]:
        return tuple(c - p for p, c in zip(self.native_preclip, self.native_clipped, strict=True))

    @property
    def saturation(self) -> tuple[bool, ...]:
        return tuple(v != 0 for v in self.residual)

    @property
    def saturated(self) -> bool:
        return any(self.saturation)

    @classmethod
    def from_native(cls, tick, observation, xr, command, preclip, clipped):
        label = np.asarray(preclip, dtype=np.float64).reshape(2, 7).copy()
        label[:, :6] = np.rad2deg(label[:, :6])
        label[:, 6] *= 1000.0
        if not np.isfinite(label).all() or not np.isfinite(clipped).all():
            raise RuntimeError("Non-finite control solution")
        with np.errstate(over="ignore"):
            canonical = label.astype("<f4")
        if not np.isfinite(canonical).all():
            raise RuntimeError("Non-finite float32 D0 label")
        return cls(
            tick, observation, xr, command, tuple(float(v) for v in preclip),
            tuple(float(v) for v in clipped), canonical.tobytes(),
        )

    def prepare(self, validator: CausalTransactionValidator):
        """Bind producer references, not pixels; 4D must freeze pixels at this boundary."""
        observation, xr = self.observation_identity, self.xr_identity
        if (observation is None or xr is None or xr.rebased
                or not all(xr.tracking_valid) or not observation.eligible):
            raise RuntimeError("Decision has no eligible observation/XR receipt")
        command = self.cartesian_intent
        if not command.session_active or any(
            not arm.tracking_valid or arm.rebased for arm in (command.left, command.right)
        ):
            raise RuntimeError("Tracking/rebase decision is not D0 eligible")
        epoch, tick = validator.epoch, self.control_tick_id
        if tick is None:
            raise RuntimeError("Decision has no eligible control tick")
        if (epoch.reset_epoch != observation.producer.reset_epoch
                or epoch.control_reference_epoch != xr.control_reference_epoch
                or epoch.source_epoch != str(xr.session_epoch)):
            raise RuntimeError("Decision epoch mismatch")
        obs_bytes = payload(asdict(observation))
        action_bytes = b"action:<f4:[14]:deg/mm:" + self.canonical_d0_action
        xr_bytes = payload(asdict(xr))
        sequences = [observation.producer.physics_step,
                     *(c.data_generation for c in observation.cameras),
                     xr.deviceio_update_epoch, xr.submitted_frame_id,
                     xr.returned_frame_id, xr.deviceio_update_epoch]
        names = ("simulation.state_generation", "camera.left_wrist", "camera.right_wrist",
                 "camera.scene", "xr.device_io_update", "xr.submitted_frame",
                 "xr.returned_frame", "xr.resolved_input")
        def bind(name, data):
            return PayloadIdentity.bind(epoch, tick, f"{epoch}:{name}:{tick}", data)
        return validator.prepare(
            bind("observation", obs_bytes), bind("action", action_bytes),
            tuple(SourceIdentity(name, bind(name, obs_bytes if i < 4 else xr_bytes), seq)
                  for i, (name, seq) in enumerate(zip(names, sequences, strict=True))),
            observation_payload=obs_bytes, action_payload=action_bytes, tracking_valid=True,
        )


def decision_epoch(run_id: str, observation: ObservationCapture, xr: ResolvedXrInput) -> Epoch:
    return Epoch(run_id, "unrecorded", "isaac_human_vr", observation.producer.reset_epoch,
                 xr.control_reference_epoch, str(xr.session_epoch))
