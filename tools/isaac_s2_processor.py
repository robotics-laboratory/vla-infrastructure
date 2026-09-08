"""Pure Gate S2 bimanual controller-state policy.

The upstream Isaac Teleop pipeline owns OpenXR acquisition, the OpenXR-to-Isaac
basis transform, and consecutive-pose delta calculation.  This module owns only
the PIPER-X-specific stateful policy around those deltas; it has no Isaac, XR, or
hardware imports so its behavior can be checked offline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Sequence

import numpy as np


PROCESSOR_REVISION = "piper_x_isaac_s2_bimanual_relative_v1"
UPSTREAM_TRANSLATION_SCALE = 10.0
UPSTREAM_ROTATION_SCALE = 10.0
DEFAULT_CLUTCH_THRESHOLD = 0.5
DEFAULT_GRIPPER_THRESHOLD = 0.5
DEFAULT_GRIPPER_APERTURE_M = 0.05
OPEN_GRIPPER_APERTURE_M = 0.1
CLOSED_GRIPPER_APERTURE_M = 0.0


@dataclass(frozen=True)
class ControllerDeltaSample:
    """One upstream relative-retargeter sample for one physical controller."""

    delta_position_m: np.ndarray
    delta_rotation_rotvec_rad: np.ndarray
    available: bool
    grip_pose_valid: bool
    squeeze_value: float
    trigger_value: float

    def __post_init__(self) -> None:
        for field_name in ("delta_position_m", "delta_rotation_rotvec_rad"):
            value = np.asarray(getattr(self, field_name), dtype=np.float64)
            if value.shape != (3,):
                raise ValueError(f"{field_name} must have shape (3,), got {value.shape}")
            object.__setattr__(self, field_name, value.copy())


@dataclass(frozen=True)
class ArmTeleopCommand:
    """Simulation-only command and state annotation for one PIPER-X arm."""

    delta_pose: np.ndarray
    gripper_aperture_m: float
    motion_active: bool
    tracking_valid: bool
    clutch_active: bool
    rebased: bool
    transition: str


@dataclass(frozen=True)
class BimanualTeleopCommand:
    left: ArmTeleopCommand
    right: ArmTeleopCommand
    session_active: bool


@dataclass(frozen=True)
class S2ProcessorConfig:
    """Small concrete configuration selected from upstream/Gate C semantics."""

    translation_scale: float = UPSTREAM_TRANSLATION_SCALE
    rotation_scale: float = UPSTREAM_ROTATION_SCALE
    clutch_threshold: float = DEFAULT_CLUTCH_THRESHOLD
    gripper_threshold: float = DEFAULT_GRIPPER_THRESHOLD
    gripper_open_m: float = OPEN_GRIPPER_APERTURE_M
    gripper_closed_m: float = CLOSED_GRIPPER_APERTURE_M
    reset_gripper_m: float = DEFAULT_GRIPPER_APERTURE_M


@dataclass
class _ArmState:
    tracking_valid: bool = False
    clutch_active: bool = False
    rebase_pending: bool = True
    gripper_aperture_m: float = DEFAULT_GRIPPER_APERTURE_M


class BimanualS2TeleopProcessor:
    """Apply independent clutch/recovery/gripper policy to two upstream streams."""

    def __init__(self, config: S2ProcessorConfig | None = None) -> None:
        self.config = config or S2ProcessorConfig()
        self._validate_config()
        self._states = {"left": _ArmState(), "right": _ArmState()}

    def _validate_config(self) -> None:
        cfg = self.config
        numeric = (
            cfg.translation_scale,
            cfg.rotation_scale,
            cfg.clutch_threshold,
            cfg.gripper_threshold,
            cfg.gripper_open_m,
            cfg.gripper_closed_m,
            cfg.reset_gripper_m,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("S2 processor configuration must be finite")
        if cfg.translation_scale <= 0.0 or cfg.rotation_scale <= 0.0:
            raise ValueError("S2 translation and rotation scales must be positive")
        if not 0.0 <= cfg.clutch_threshold <= 1.0:
            raise ValueError("clutch_threshold must be in [0, 1]")
        if not 0.0 <= cfg.gripper_threshold <= 1.0:
            raise ValueError("gripper_threshold must be in [0, 1]")
        if not cfg.gripper_closed_m <= cfg.reset_gripper_m <= cfg.gripper_open_m:
            raise ValueError("reset gripper aperture must lie between closed and open")

    def reset(self) -> None:
        """Clear episode/session state and require a fresh valid rebase per arm."""

        self._states = {
            side: _ArmState(gripper_aperture_m=self.config.reset_gripper_m)
            for side in ("left", "right")
        }

    def session_inactive(self) -> BimanualTeleopCommand:
        """Enter the safe simulation hold state without replaying stale intent."""

        commands = {}
        for side in ("left", "right"):
            state = self._states[side]
            state.tracking_valid = False
            state.clutch_active = False
            state.rebase_pending = True
            commands[side] = self._hold(state, "session_inactive")
        return BimanualTeleopCommand(commands["left"], commands["right"], False)

    def advance(
        self,
        left: ControllerDeltaSample,
        right: ControllerDeltaSample,
        *,
        session_active: bool = True,
    ) -> BimanualTeleopCommand:
        if not session_active:
            return self.session_inactive()
        return BimanualTeleopCommand(
            self._advance_arm("left", left),
            self._advance_arm("right", right),
            True,
        )

    def _advance_arm(
        self, side: Literal["left", "right"], sample: ControllerDeltaSample
    ) -> ArmTeleopCommand:
        state = self._states[side]
        finite = bool(
            np.isfinite(sample.delta_position_m).all()
            and np.isfinite(sample.delta_rotation_rotvec_rad).all()
            and math.isfinite(sample.squeeze_value)
            and math.isfinite(sample.trigger_value)
        )
        tracked = sample.available and sample.grip_pose_valid and finite
        if not tracked:
            transition = "tracking_lost" if state.tracking_valid else "tracking_invalid"
            state.tracking_valid = False
            state.clutch_active = False
            state.rebase_pending = True
            return self._hold(state, transition)

        state.gripper_aperture_m = (
            self.config.gripper_closed_m
            if sample.trigger_value > self.config.gripper_threshold
            else self.config.gripper_open_m
        )
        clutch = sample.squeeze_value > self.config.clutch_threshold

        if state.rebase_pending:
            state.rebase_pending = False
            state.tracking_valid = True
            state.clutch_active = clutch
            return self._hold(state, "tracking_rebased", rebased=True)

        if clutch:
            transition = "clutch_engaged" if not state.clutch_active else "clutch_held"
            state.tracking_valid = True
            state.clutch_active = True
            return self._hold(state, transition)

        if state.clutch_active:
            state.tracking_valid = True
            state.clutch_active = False
            return self._hold(state, "clutch_release_rebased", rebased=True)

        state.tracking_valid = True
        delta = np.concatenate(
            (
                sample.delta_position_m * self.config.translation_scale,
                sample.delta_rotation_rotvec_rad * self.config.rotation_scale,
            )
        )
        return ArmTeleopCommand(
            delta_pose=delta,
            gripper_aperture_m=state.gripper_aperture_m,
            motion_active=bool(np.any(delta)),
            tracking_valid=True,
            clutch_active=False,
            rebased=False,
            transition="motion",
        )

    @staticmethod
    def _hold(
        state: _ArmState, transition: str, *, rebased: bool = False
    ) -> ArmTeleopCommand:
        return ArmTeleopCommand(
            delta_pose=np.zeros(6, dtype=np.float64),
            gripper_aperture_m=state.gripper_aperture_m,
            motion_active=False,
            tracking_valid=state.tracking_valid,
            clutch_active=state.clutch_active,
            rebased=rebased,
            transition=transition,
        )


def controller_pose_delta_xyzw(
    previous_pose: Sequence[float], current_pose: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Reference the upstream spatial-delta convention for synthetic tests.

    Poses are ``[x, y, z, qx, qy, qz, qw]`` in the already transformed Isaac
    frame. Rotation is ``R_current * inverse(R_previous)`` and is returned as a
    world/spatial rotation vector, matching `Se3RelRetargeter`.
    """

    previous = _pose(previous_pose, "previous_pose")
    current = _pose(current_pose, "current_pose")
    relative = _quat_multiply_xyzw(current[3:], _quat_conjugate_xyzw(previous[3:]))
    relative /= np.linalg.norm(relative)
    if relative[3] < 0.0:
        relative = -relative
    vector_norm = float(np.linalg.norm(relative[:3]))
    rotation_vector: np.ndarray
    if vector_norm < 1.0e-12:
        rotation_vector = np.zeros(3, dtype=np.float64)
    else:
        angle = 2.0 * math.atan2(vector_norm, float(relative[3]))
        rotation_vector = relative[:3] * (angle / vector_norm)
    return current[:3] - previous[:3], rotation_vector


def _pose(value: Sequence[float], name: str) -> np.ndarray:
    pose = np.asarray(value, dtype=np.float64)
    if pose.shape != (7,) or not np.isfinite(pose).all():
        raise ValueError(f"{name} must be a finite seven-element XYZW pose")
    quaternion_norm = float(np.linalg.norm(pose[3:]))
    if quaternion_norm == 0.0:
        raise ValueError(f"{name} has a zero quaternion")
    pose = pose.copy()
    pose[3:] /= quaternion_norm
    return pose


def _quat_conjugate_xyzw(quaternion: np.ndarray) -> np.ndarray:
    return np.asarray([-quaternion[0], -quaternion[1], -quaternion[2], quaternion[3]])


def _quat_multiply_xyzw(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return np.asarray(
        [
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ],
        dtype=np.float64,
    )


def unpack_pipeline_action(values: Sequence[float]) -> tuple[ControllerDeltaSample, ControllerDeltaSample]:
    """Decode the one fixed S2 upstream pipeline layout."""

    action = np.asarray(values, dtype=np.float64)
    if action.shape != (20,):
        raise ValueError(f"S2 upstream action must have shape (20,), got {action.shape}")

    def arm(offset: int) -> ControllerDeltaSample:
        controls = action[offset + 6 : offset + 10]
        return ControllerDeltaSample(
            delta_position_m=action[offset : offset + 3],
            delta_rotation_rotvec_rad=action[offset + 3 : offset + 6],
            available=bool(controls[0] > 0.5),
            grip_pose_valid=bool(controls[1] > 0.5),
            squeeze_value=float(controls[2]),
            trigger_value=float(controls[3]),
        )

    return arm(0), arm(10)
