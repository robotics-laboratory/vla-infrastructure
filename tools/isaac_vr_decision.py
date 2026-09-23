"""In-memory Isaac human decision receipts; no acquisition clock or storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Any

import numpy as np

from tools.d0_causal import (
    CausalTransactionValidator,
    CompletedTransition,
    Epoch,
    PayloadIdentity,
    PreparedTransaction,
    SourceIdentity,
)
from tools.isaac_vr_capture import ObservationCapture

DECISION_REVISION = "piper_x_xr_preclip_decision_v1"


def recordable_teleop_command(command: Any) -> bool:
    """Only a fully tracked motion decision may enter a D0 episode.

    Clutch, tracking recovery, sensitivity changes and other processor holds
    remain operator/control events, not invented zero-action training rows.
    A motion decision may still have a genuinely zero-valued native action.
    """
    return bool(
        command.session_active
        and all(
            arm.tracking_valid
            and not arm.rebased
            and not arm.clutch_active
            and arm.transition == "motion"
            for arm in (command.left, command.right)
        )
    )


def _is_live_observation(observation: Any) -> bool:
    """Recognize the live capture structurally across supported import aliases.

    Isaac's script entrypoint can load ``isaac_vr_capture`` while the shared
    decision module is imported as ``tools.isaac_vr_decision``.  Those aliases
    create distinct Python class objects even though they describe the same
    frozen receipt, so runtime identity must not depend on ``isinstance``.
    """

    return hasattr(observation, "producer")


def _observation_reset_epoch(
    observation: ObservationCapture | StateSnapshotObservation,
) -> int:
    if _is_live_observation(observation):
        return int(observation.producer.reset_epoch)
    return int(observation.reset_epoch)


def payload(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _float32_vector(value: Any, *, size: int, field: str) -> np.ndarray:
    array = np.asarray(value, dtype="<f4")
    if array.shape != (size,) or not np.isfinite(array).all():
        raise ValueError(f"{field} must be finite float32[{size}]")
    return array


def _sha256_hex(value: str, *, field: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be lowercase SHA-256 hex")
    return value


def canonical_state_snapshot_payload(
    *,
    reset_epoch: int,
    physics_step: int,
    state_generation: int,
    capture_sequence: int,
    scene_state_snapshot_id: str,
    scene_state_snapshot_sha256: str,
    state: Any,
) -> bytes:
    """Canonical payload shared by the validator identity and stored HDF row."""
    values = {
        "reset_epoch": reset_epoch,
        "physics_step": physics_step,
        "state_generation": state_generation,
        "capture_sequence": capture_sequence,
    }
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("state snapshot boundary fields must be nonnegative integers")
    if not scene_state_snapshot_id:
        raise ValueError("scene_state_snapshot_id must be non-empty")
    digest = _sha256_hex(scene_state_snapshot_sha256, field="scene_state_snapshot_sha256")
    state_f32 = _float32_vector(state, size=14, field="observation_state")
    return payload(
        {
            "capture_sequence": capture_sequence,
            "physics_step": physics_step,
            "reset_epoch": reset_epoch,
            "scene_state_snapshot_id": scene_state_snapshot_id,
            "scene_state_snapshot_sha256": digest,
            "schema": "piper_x_scene_state_observation_v1",
            "state": state_f32.tolist(),
            "state_dtype": "<f4",
            "state_generation": state_generation,
            "state_units": "ordered_joint_degrees_gripper_millimetres",
        }
    )


def canonical_action_payload(
    dataset_action: Any,
    *,
    processor_revision: str,
    provenance_revision: str,
    processor_generation: int,
) -> bytes:
    if not processor_revision or not provenance_revision or processor_generation < 0:
        raise ValueError("invalid action processor identity")
    action_f32 = _float32_vector(dataset_action, size=14, field="dataset_action")
    return payload(
        {
            "action": action_f32.tolist(),
            "action_dtype": "<f4",
            "action_units": "ordered_joint_degrees_gripper_millimetres",
            "processor_generation": processor_generation,
            "processor_revision": processor_revision,
            "provenance_revision": provenance_revision,
            "schema": "piper_x_dataset_action_v1",
        }
    )


def canonical_native_command_payload(
    *, preclip: Any, clipped: Any, residual: Any, saturation: Any
) -> bytes:
    preclip_f32 = _float32_vector(preclip, size=14, field="native_preclip")
    clipped_f32 = _float32_vector(clipped, size=14, field="native_clipped")
    residual_f32 = _float32_vector(residual, size=14, field="native_residual")
    saturation_u8 = np.asarray(saturation, dtype=np.uint8)
    if saturation_u8.shape != (14,) or not np.isin(saturation_u8, (0, 1)).all():
        raise ValueError("saturation must be uint8[14] boolean flags")
    expected_residual = clipped_f32 - preclip_f32
    if not np.array_equal(residual_f32, expected_residual):
        raise ValueError("native residual must be the exact stored float32 clipped-preclip delta")
    if not np.array_equal(saturation_u8, (residual_f32 != 0).astype(np.uint8)):
        raise ValueError("native saturation must match the exact stored float32 residual")
    return payload(
        {
            "clipped": clipped_f32.tolist(),
            "dtype": "<f4",
            "preclip": preclip_f32.tolist(),
            "residual": residual_f32.tolist(),
            "saturation": saturation_u8.tolist(),
            "schema": "piper_x_native_command_v1",
            "units": "ordered_joint_radians_gripper_metres",
        }
    )


def canonical_native_command_fields(*, preclip: Any, clipped: Any) -> dict[str, np.ndarray]:
    preclip_f32 = _float32_vector(preclip, size=14, field="native_preclip")
    clipped_f32 = _float32_vector(clipped, size=14, field="native_clipped")
    residual_f32 = clipped_f32 - preclip_f32
    return {
        "preclip": preclip_f32,
        "clipped": clipped_f32,
        "residual": residual_f32,
        "saturation": (residual_f32 != 0).astype(np.uint8),
    }


def canonical_hands_sha256(hands: Any) -> str:
    return sha256(payload(hands)).hexdigest()


def canonical_xr_payload_from_fields(
    *,
    session_epoch: int,
    control_reference_epoch: int,
    deviceio_update_epoch: int,
    submitted_frame_id: int,
    returned_frame_id: int,
    ran_synchronously: bool,
    rebased: bool,
    tracking_valid: Any,
    world_transform: Any,
    hands_sha256: str,
) -> bytes:
    counters = {
        "session_epoch": session_epoch,
        "control_reference_epoch": control_reference_epoch,
        "deviceio_update_epoch": deviceio_update_epoch,
        "submitted_frame_id": submitted_frame_id,
        "returned_frame_id": returned_frame_id,
    }
    if any(type(value) is not int or value < 0 for value in counters.values()):
        raise ValueError("XR counters must be nonnegative integers")
    tracking = np.asarray(tracking_valid, dtype=np.uint8)
    if tracking.shape != (2,) or not np.isin(tracking, (0, 1)).all():
        raise ValueError("tracking_valid must be two boolean flags")
    transform = _float32_vector(world_transform, size=16, field="xr_world_transform")
    return payload(
        {
            **counters,
            "hands_sha256": _sha256_hex(hands_sha256, field="hands_sha256"),
            "ran_synchronously": bool(ran_synchronously),
            "rebased": bool(rebased),
            "schema": "piper_x_resolved_xr_input_v1",
            "tracking_valid": tracking.tolist(),
            "world_transform": transform.tolist(),
            "world_transform_dtype": "<f4",
        }
    )


def canonical_xr_payload(xr: "ResolvedXrInput") -> bytes:
    return canonical_xr_payload_from_fields(
        session_epoch=xr.session_epoch,
        control_reference_epoch=xr.control_reference_epoch,
        deviceio_update_epoch=xr.deviceio_update_epoch,
        submitted_frame_id=xr.submitted_frame_id,
        returned_frame_id=xr.returned_frame_id,
        ran_synchronously=xr.ran_synchronously,
        rebased=xr.rebased,
        tracking_valid=xr.tracking_valid,
        world_transform=xr.world_transform,
        hands_sha256=canonical_hands_sha256(xr.hands),
    )


def _payload_id(epoch: Epoch, role: str, tick: int) -> str:
    return ":".join(
        (
            epoch.run_id,
            epoch.episode_id,
            epoch.source_id,
            str(epoch.reset_epoch),
            str(epoch.control_reference_epoch),
            epoch.source_epoch,
            role,
            str(tick),
        )
    )


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


@dataclass(frozen=True)
class StateSnapshotObservation:
    """Immutable native state boundary used by the offline-RGB recording profile."""

    reset_epoch: int
    physics_step: int
    state_generation: int
    state: tuple[float, ...]
    capture_sequence: int | None = None
    scene_state_snapshot_id: str | None = None
    scene_state_snapshot_sha256: str | None = None

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.reset_epoch, self.physics_step, self.state_generation)
        ):
            raise ValueError("invalid state snapshot identity")
        if len(self.state) != 14 or not np.isfinite(self.state).all():
            raise ValueError("invalid state snapshot payload")
        binding = (
            self.capture_sequence,
            self.scene_state_snapshot_id,
            self.scene_state_snapshot_sha256,
        )
        if any(value is not None for value in binding):
            if (
                type(self.capture_sequence) is not int
                or self.capture_sequence < 0
                or not self.scene_state_snapshot_id
                or self.scene_state_snapshot_sha256 is None
            ):
                raise ValueError("state snapshot recording binding must be complete")
            _sha256_hex(self.scene_state_snapshot_sha256, field="scene_state_snapshot_sha256")

    @property
    def recording_bound(self) -> bool:
        return self.capture_sequence is not None

    def bind_recording_snapshot(
        self, *, capture_sequence: int, snapshot_id: str, snapshot_sha256: str
    ) -> "StateSnapshotObservation":
        if self.recording_bound:
            raise ValueError("state observation is already bound to a recorder snapshot")
        return replace(
            self,
            capture_sequence=capture_sequence,
            scene_state_snapshot_id=snapshot_id,
            scene_state_snapshot_sha256=snapshot_sha256,
        )

    def canonical_payload(self) -> bytes:
        if not self.recording_bound:
            raise RuntimeError("state observation is not bound to a full recorder snapshot")
        assert self.capture_sequence is not None
        assert self.scene_state_snapshot_id is not None
        assert self.scene_state_snapshot_sha256 is not None
        return canonical_state_snapshot_payload(
            reset_epoch=self.reset_epoch,
            physics_step=self.physics_step,
            state_generation=self.state_generation,
            capture_sequence=self.capture_sequence,
            scene_state_snapshot_id=self.scene_state_snapshot_id,
            scene_state_snapshot_sha256=self.scene_state_snapshot_sha256,
            state=self.state,
        )


def capture_state_snapshot(env: Any) -> StateSnapshotObservation:
    """Capture one stable native state generation without reading live RGB."""

    physics_step, state = env.capture_measured_state()
    reset_epoch = int(env.camera.reset_epoch)
    state_generation = int(env._state_physics_step)
    snapshot = StateSnapshotObservation(
        reset_epoch, int(physics_step), state_generation, tuple(float(value) for value in state)
    )
    check_observation(env, snapshot)
    return snapshot


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
        if (
            self.update_epoch != previous_update + 1
            or self.hands is None
            or not info.ran_synchronously
            or info.worker_exception is not None
            or info.submitted_frame_id != self.frame
            or info.returned_frame_id != self.frame
        ):
            raise RuntimeError("XR update/request/result mismatch")
        return ResolvedXrInput(
            self.session_epoch,
            self.reference_epoch,
            self.update_epoch,
            self.frame,
            self.frame,
            True,
            self.hands,
            self.transform,
            self.rebased,
            self.tracking_valid,
        )

    def validate(self, xr: ResolvedXrInput) -> None:
        if (
            xr.session_epoch != self.session_epoch
            or xr.control_reference_epoch != self.reference_epoch
            or xr.deviceio_update_epoch != self.update_epoch
            or xr.deviceio_update_epoch <= self.last_consumed
        ):
            raise RuntimeError("XR session/reference/update changed or reused")


def check_observation(
    env: Any, observation: ObservationCapture | StateSnapshotObservation | None
) -> None:
    if observation is None:
        return
    if isinstance(observation, StateSnapshotObservation):
        physics_step, state = env.capture_measured_state()
        if (
            int(env.camera.reset_epoch) != observation.reset_epoch
            or int(physics_step) != observation.physics_step
            or int(env._state_physics_step) != observation.state_generation
            or env.sim.get_physics_step_count() != observation.physics_step
            or tuple(float(value) for value in state) != observation.state
        ):
            raise RuntimeError("IK observation/state generation mismatch")
        return
    if (
        env.latest_observation_capture() is not observation
        or env._state_physics_step != observation.producer.physics_step
        or env.sim.get_physics_step_count() != observation.producer.physics_step
    ):
        raise RuntimeError("IK observation/state generation mismatch")


@dataclass(frozen=True)
class SolvedControlDecision:
    control_tick_id: int | None  # None for ordinary RUN holds outside D0 admission.
    observation_identity: ObservationCapture | StateSnapshotObservation | None
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
            tick,
            observation,
            xr,
            command,
            tuple(float(v) for v in preclip),
            tuple(float(v) for v in clipped),
            canonical.tobytes(),
        )

    def prepare(self, validator: CausalTransactionValidator):
        """Bind the selected live-camera or immutable-state observation profile."""
        observation, xr = self.observation_identity, self.xr_identity
        if (
            observation is None
            or xr is None
            or xr.rebased
            or not all(xr.tracking_valid)
            or (_is_live_observation(observation) and not observation.eligible)
        ):
            raise RuntimeError("Decision has no eligible observation/XR receipt")
        command = self.cartesian_intent
        if not recordable_teleop_command(command):
            raise RuntimeError("Tracking/rebase/hold decision is not D0 eligible")
        epoch, tick = validator.epoch, self.control_tick_id
        if tick is None:
            raise RuntimeError("Decision has no eligible control tick")
        reset_epoch = _observation_reset_epoch(observation)
        if (
            epoch.reset_epoch != reset_epoch
            or epoch.control_reference_epoch != xr.control_reference_epoch
            or epoch.source_epoch != str(xr.session_epoch)
        ):
            raise RuntimeError("Decision epoch mismatch")
        obs_bytes = self.observation_payload
        action_bytes = self.action_payload
        xr_bytes = canonical_xr_payload(xr)
        if isinstance(observation, StateSnapshotObservation):
            if validator.profile != "isaac_human_vr_offline_rgb_v1":
                raise RuntimeError("State snapshot observation requires offline-RGB profile")
            sequences = [
                observation.state_generation,
                xr.deviceio_update_epoch,
                xr.submitted_frame_id,
                xr.returned_frame_id,
                xr.deviceio_update_epoch,
            ]
            names = (
                "simulation.scene_state_snapshot",
                "xr.device_io_update",
                "xr.submitted_frame",
                "xr.returned_frame",
                "xr.resolved_input",
            )
            source_payloads = (obs_bytes, xr_bytes, xr_bytes, xr_bytes, xr_bytes)
        else:
            if validator.profile != "isaac_human_vr_v4":
                raise RuntimeError("Live camera observation requires live-camera profile")
            sequences = [
                observation.producer.physics_step,
                *(c.data_generation for c in observation.cameras),
                xr.deviceio_update_epoch,
                xr.submitted_frame_id,
                xr.returned_frame_id,
                xr.deviceio_update_epoch,
            ]
            names = (
                "simulation.state_generation",
                "camera.left_wrist",
                "camera.right_wrist",
                "camera.scene",
                "xr.device_io_update",
                "xr.submitted_frame",
                "xr.returned_frame",
                "xr.resolved_input",
            )
            source_payloads = (
                obs_bytes,
                obs_bytes,
                obs_bytes,
                obs_bytes,
                xr_bytes,
                xr_bytes,
                xr_bytes,
                xr_bytes,
            )

        def bind(name, data):
            return PayloadIdentity.bind(epoch, tick, _payload_id(epoch, name, tick), data)

        return validator.prepare(
            bind("observation", obs_bytes),
            bind("action", action_bytes),
            tuple(
                SourceIdentity(name, bind(name, source_payload), sequence)
                for name, sequence, source_payload in zip(
                    names, sequences, source_payloads, strict=True
                )
            ),
            observation_payload=obs_bytes,
            action_payload=action_bytes,
            tracking_valid=True,
        )

    @property
    def observation_payload(self) -> bytes:
        if self.observation_identity is None:
            raise RuntimeError("Decision has no observation payload")
        if isinstance(self.observation_identity, StateSnapshotObservation):
            return self.observation_identity.canonical_payload()
        return payload(asdict(self.observation_identity))

    @property
    def action_payload(self) -> bytes:
        processor_revision, provenance_revision, generation = self.processor_identity
        return canonical_action_payload(
            self.dataset_action,
            processor_revision=processor_revision,
            provenance_revision=provenance_revision,
            processor_generation=generation,
        )


@dataclass(frozen=True)
class CommittedRecordingTransition:
    """Validated transition plus the exact payloads needed by the HDF writer."""

    prepared: PreparedTransaction
    completed: CompletedTransition
    successor_observation: StateSnapshotObservation
    observation_payload: bytes
    action_payload: bytes
    native_command_payload: bytes
    successor_payload: bytes


def commit_recording_transition(
    validator: CausalTransactionValidator,
    decision: SolvedControlDecision,
    prepared: PreparedTransaction,
    successor: StateSnapshotObservation,
    *,
    physics_steps: int = 4,
) -> CommittedRecordingTransition:
    """Complete and commit one applied offline-RGB transition, fail closed."""

    observation = decision.observation_identity
    if not isinstance(observation, StateSnapshotObservation):
        raise RuntimeError("Recording commit requires a state snapshot observation")
    if prepared.observation.control_tick_id != decision.control_tick_id:
        raise RuntimeError("Prepared transaction does not belong to decision")
    if (
        successor.reset_epoch != observation.reset_epoch
        or successor.physics_step != observation.physics_step + physics_steps
        or successor.state_generation != successor.physics_step
    ):
        raise RuntimeError("Successor does not match the applied physics transition")
    tick = prepared.observation.control_tick_id
    epoch = validator.epoch
    native_fields = canonical_native_command_fields(
        preclip=decision.native_preclip, clipped=decision.native_clipped
    )
    native_command_payload = canonical_native_command_payload(**native_fields)
    successor_payload = successor.canonical_payload()
    native = PayloadIdentity.bind(
        epoch, tick, _payload_id(epoch, "native", tick), native_command_payload
    )
    successor_identity = PayloadIdentity.bind(
        epoch,
        tick + 1,
        _payload_id(epoch, "observation", tick + 1),
        successor_payload,
    )
    completed = validator.complete_transition(
        prepared,
        native,
        _payload_id(epoch, "transition", tick),
        successor_identity,
        successful=True,
    )
    observation_payload = decision.observation_payload
    action_payload = decision.action_payload
    validator.commit(
        prepared,
        observation_payload=observation_payload,
        action_payload=action_payload,
    )
    return CommittedRecordingTransition(
        prepared,
        completed,
        successor,
        observation_payload,
        action_payload,
        native_command_payload,
        successor_payload,
    )


def decision_epoch(
    run_id: str,
    observation: ObservationCapture | StateSnapshotObservation,
    xr: ResolvedXrInput,
    *,
    episode_id: str = "unrecorded",
) -> Epoch:
    reset_epoch = _observation_reset_epoch(observation)
    return Epoch(
        run_id,
        episode_id,
        "isaac_human_vr",
        reset_epoch,
        xr.control_reference_epoch,
        str(xr.session_epoch),
    )
