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


PROCESSOR_REVISION = "piper_x_isaac_s2_bimanual_relative_v2"
NORMAL_TRANSLATION_SCALE = 2.0
NORMAL_ROTATION_SCALE = 2.0
PRECISE_TRANSLATION_SCALE = 0.5
PRECISE_ROTATION_SCALE = 0.5
DEFAULT_CLUTCH_THRESHOLD = 0.5
DEFAULT_SENSITIVITY_TOGGLE_THRESHOLD = 0.5
DEFAULT_GRIPPER_APERTURE_M = 0.05
OPEN_GRIPPER_APERTURE_M = 0.1
CLOSED_GRIPPER_APERTURE_M = 0.0

SensitivityMode = Literal["normal", "precise"]


@dataclass(frozen=True)
class ControllerDeltaSample:
    """One upstream relative-retargeter sample for one physical controller."""

    delta_position_m: np.ndarray
    delta_rotation_rotvec_rad: np.ndarray
    available: bool
    grip_pose_valid: bool
    squeeze_value: float
    trigger_value: float
    sensitivity_button_value: float

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
    sensitivity_mode: SensitivityMode
    transition: str


@dataclass(frozen=True)
class BimanualTeleopCommand:
    left: ArmTeleopCommand
    right: ArmTeleopCommand
    session_active: bool


@dataclass(frozen=True)
class S2ProcessorConfig:
    """Small concrete configuration selected from upstream/Gate C semantics."""

    normal_translation_scale: float = NORMAL_TRANSLATION_SCALE
    normal_rotation_scale: float = NORMAL_ROTATION_SCALE
    precise_translation_scale: float = PRECISE_TRANSLATION_SCALE
    precise_rotation_scale: float = PRECISE_ROTATION_SCALE
    initial_sensitivity_mode: SensitivityMode = "normal"
    sensitivity_toggle_threshold: float = DEFAULT_SENSITIVITY_TOGGLE_THRESHOLD
    clutch_threshold: float = DEFAULT_CLUTCH_THRESHOLD
    gripper_trigger_min: float = 0.0
    gripper_trigger_max: float = 1.0
    gripper_open_m: float = OPEN_GRIPPER_APERTURE_M
    gripper_closed_m: float = CLOSED_GRIPPER_APERTURE_M
    reset_gripper_m: float = DEFAULT_GRIPPER_APERTURE_M


@dataclass
class _ArmState:
    tracking_valid: bool = False
    clutch_active: bool = False
    rebase_pending: bool = True
    gripper_aperture_m: float = DEFAULT_GRIPPER_APERTURE_M
    sensitivity_mode: SensitivityMode = "normal"
    sensitivity_button_pressed: bool = False


class BimanualS2TeleopProcessor:
    """Apply independent clutch/recovery/gripper policy to two upstream streams."""

    def __init__(self, config: S2ProcessorConfig | None = None) -> None:
        self.config = config or S2ProcessorConfig()
        self._validate_config()
        self._states = {side: self._new_state() for side in ("left", "right")}

    def _validate_config(self) -> None:
        cfg = self.config
        numeric = (
            cfg.normal_translation_scale,
            cfg.normal_rotation_scale,
            cfg.precise_translation_scale,
            cfg.precise_rotation_scale,
            cfg.sensitivity_toggle_threshold,
            cfg.clutch_threshold,
            cfg.gripper_trigger_min,
            cfg.gripper_trigger_max,
            cfg.gripper_open_m,
            cfg.gripper_closed_m,
            cfg.reset_gripper_m,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("S2 processor configuration must be finite")
        scales = (
            cfg.normal_translation_scale,
            cfg.normal_rotation_scale,
            cfg.precise_translation_scale,
            cfg.precise_rotation_scale,
        )
        if not all(value > 0.0 for value in scales):
            raise ValueError("S2 translation and rotation scales must be positive")
        if cfg.initial_sensitivity_mode not in ("normal", "precise"):
            raise ValueError("initial_sensitivity_mode must be normal or precise")
        if not 0.0 <= cfg.sensitivity_toggle_threshold <= 1.0:
            raise ValueError("sensitivity_toggle_threshold must be in [0, 1]")
        if not 0.0 <= cfg.clutch_threshold <= 1.0:
            raise ValueError("clutch_threshold must be in [0, 1]")
        if not cfg.gripper_trigger_min < cfg.gripper_trigger_max:
            raise ValueError("gripper trigger maximum must exceed its minimum")
        if cfg.gripper_open_m < cfg.gripper_closed_m:
            raise ValueError("open gripper aperture must not be below closed")
        if not cfg.gripper_closed_m <= cfg.reset_gripper_m <= cfg.gripper_open_m:
            raise ValueError("reset gripper aperture must lie between closed and open")

    def _new_state(self) -> _ArmState:
        return _ArmState(
            gripper_aperture_m=self.config.reset_gripper_m,
            sensitivity_mode=self.config.initial_sensitivity_mode,
        )

    def reset(self) -> None:
        """Clear episode/session state and require a fresh valid rebase per arm."""

        self._states = {side: self._new_state() for side in ("left", "right")}

    def session_inactive(self) -> BimanualTeleopCommand:
        """Enter the safe simulation hold state without replaying stale intent."""

        commands = {}
        for side in ("left", "right"):
            state = self._states[side]
            state.tracking_valid = False
            state.clutch_active = False
            state.rebase_pending = True
            state.sensitivity_button_pressed = False
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
            and math.isfinite(sample.sensitivity_button_value)
        )
        tracked = sample.available and sample.grip_pose_valid and finite
        if not tracked:
            transition = "tracking_lost" if state.tracking_valid else "tracking_invalid"
            state.tracking_valid = False
            state.clutch_active = False
            state.rebase_pending = True
            return self._hold(state, transition)

        trigger_fraction = (sample.trigger_value - self.config.gripper_trigger_min) / (
            self.config.gripper_trigger_max - self.config.gripper_trigger_min
        )
        trigger_fraction = min(1.0, max(0.0, trigger_fraction))
        state.gripper_aperture_m = self.config.gripper_open_m + trigger_fraction * (
            self.config.gripper_closed_m - self.config.gripper_open_m
        )
        clutch = sample.squeeze_value > self.config.clutch_threshold
        sensitivity_pressed = (
            sample.sensitivity_button_value > self.config.sensitivity_toggle_threshold
        )

        if state.rebase_pending:
            state.rebase_pending = False
            state.tracking_valid = True
            state.clutch_active = clutch
            # A held button on recovery is not a fresh user toggle.
            state.sensitivity_button_pressed = sensitivity_pressed
            return self._hold(state, "tracking_rebased", rebased=True)

        sensitivity_toggled = sensitivity_pressed and not state.sensitivity_button_pressed
        state.sensitivity_button_pressed = sensitivity_pressed
        if sensitivity_toggled:
            state.sensitivity_mode = "precise" if state.sensitivity_mode == "normal" else "normal"
            state.tracking_valid = True
            state.clutch_active = clutch
            return self._hold(state, f"sensitivity_switched_{state.sensitivity_mode}")

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
        translation_scale, rotation_scale = self._active_scales(state)
        delta = np.concatenate(
            (
                sample.delta_position_m * translation_scale,
                sample.delta_rotation_rotvec_rad * rotation_scale,
            )
        )
        return ArmTeleopCommand(
            delta_pose=delta,
            gripper_aperture_m=state.gripper_aperture_m,
            motion_active=bool(np.any(delta)),
            tracking_valid=True,
            clutch_active=False,
            rebased=False,
            sensitivity_mode=state.sensitivity_mode,
            transition="motion",
        )

    def _active_scales(self, state: _ArmState) -> tuple[float, float]:
        if state.sensitivity_mode == "precise":
            return (
                self.config.precise_translation_scale,
                self.config.precise_rotation_scale,
            )
        return (
            self.config.normal_translation_scale,
            self.config.normal_rotation_scale,
        )

    @staticmethod
    def _hold(state: _ArmState, transition: str, *, rebased: bool = False) -> ArmTeleopCommand:
        return ArmTeleopCommand(
            delta_pose=np.zeros(6, dtype=np.float64),
            gripper_aperture_m=state.gripper_aperture_m,
            motion_active=False,
            tracking_valid=state.tracking_valid,
            clutch_active=state.clutch_active,
            rebased=rebased,
            sensitivity_mode=state.sensitivity_mode,
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


def unpack_pipeline_action(
    values: Sequence[float],
) -> tuple[ControllerDeltaSample, ControllerDeltaSample]:
    """Decode the one fixed S2 upstream pipeline layout."""

    action = np.asarray(values, dtype=np.float64)
    if action.shape != (22,):
        raise ValueError(f"S2 upstream action must have shape (22,), got {action.shape}")

    def arm(offset: int) -> ControllerDeltaSample:
        controls = action[offset + 6 : offset + 11]
        return ControllerDeltaSample(
            delta_position_m=action[offset : offset + 3],
            delta_rotation_rotvec_rad=action[offset + 3 : offset + 6],
            available=bool(controls[0] > 0.5),
            grip_pose_valid=bool(controls[1] > 0.5),
            squeeze_value=float(controls[2]),
            trigger_value=float(controls[3]),
            sensitivity_button_value=float(controls[4]),
        )

    return arm(0), arm(11)
