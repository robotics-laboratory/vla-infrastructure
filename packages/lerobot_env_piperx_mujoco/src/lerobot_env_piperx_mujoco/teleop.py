"""Pure Quest-delta to D0 adapter for the concrete PIPER-X MuJoCo task."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import numpy as np

from .constants import JOINT_LIMITS_DEG, SIDES


TELEOP_PROCESSOR_REVISION = "piperx_mujoco_quest_ik_d0_v18"
CONTROLLER_TO_SCENE = np.asarray(
    [
        [0.0, 0.0, -1.0],
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=np.float64,
)


@dataclass(frozen=True)
class QuestIkConfig:
    position_weight: float = 1.0
    # Preserve the accepted target orientation while translating. Physical
    # v34 showed that feeding controller rotation into this task accumulates
    # large wrist excursions, whereas disabling the orientation task entirely
    # leaves translation underconstrained and produces straight-arm motion.
    orientation_weight: float = 0.01
    controller_rotation_enabled: bool = True
    rotation_activation_threshold_rad: float = 0.006
    iterations_per_tick: int = 4
    max_translation_delta_m: float = 0.05
    max_rotation_delta_rad: float = 0.05
    max_joint_step_deg: float = 8.0
    max_joint_tracking_error_deg: float = 25.0
    minimum_translation_alignment: float = 0.5
    max_gripper_step_mm: float = 10.0
    gripper_arm_open_threshold_mm: float = 95.0


@dataclass(frozen=True)
class QuestGripperActuatorConfig:
    aperture_kp: float = 1250.0
    aperture_kv: float = 45.0
    aperture_force_limit_n: float = 8.0
    finger_armature_kg: float = 0.1
    finger_damping_n_s_m: float = 2.0
    center_constraint_timeconst_s: float = 0.02
    center_constraint_damping_ratio: float = 1.0


@dataclass(frozen=True)
class QuestIkResult:
    d0_action: np.ndarray
    saturation_mask: np.ndarray
    cartesian_delta_clipped: dict[str, bool]
    ik_failed: dict[str, bool]
    target_tracking_error_deg: dict[str, float]
    gripper_target_error_mm: dict[str, float]
    gripper_armed: dict[str, bool]
    translation_alignment: dict[str, float | None]
    achieved_translation_m: dict[str, list[float]]

    @property
    def saturated(self) -> bool:
        return bool(self.saturation_mask.any() or any(self.cartesian_delta_clipped.values()))

    @property
    def joint_saturated(self) -> bool:
        return bool(self.saturation_mask[[*range(6), *range(7, 13)]].any())

    @property
    def gripper_saturated(self) -> bool:
        return bool(self.saturation_mask[[6, 13]].any())

    @property
    def cartesian_saturated(self) -> bool:
        return any(self.cartesian_delta_clipped.values())


def controller_delta_to_scene(delta_pose: Iterable[float]) -> np.ndarray:
    """Rotate the controller delta into M1 forward/left/up world axes."""

    delta = np.asarray(delta_pose, dtype=np.float64)
    if delta.shape != (6,) or not np.isfinite(delta).all():
        raise ValueError("Quest controller delta must be one finite six-element vector")
    return np.concatenate(
        (CONTROLLER_TO_SCENE @ delta[:3], CONTROLLER_TO_SCENE @ delta[3:])
    )


def _rotation_from_rotvec(rotvec: np.ndarray) -> np.ndarray:
    angle = float(np.linalg.norm(rotvec))
    if angle < 1.0e-12:
        return np.eye(3, dtype=np.float64)
    axis = rotvec / angle
    skew = np.asarray(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ],
        dtype=np.float64,
    )
    return np.eye(3) + math.sin(angle) * skew + (1.0 - math.cos(angle)) * (skew @ skew)


def _clip_vector_norm(value: np.ndarray, maximum: float) -> tuple[np.ndarray, bool]:
    norm = float(np.linalg.norm(value))
    if norm <= maximum or norm == 0.0:
        return value, False
    return value * (maximum / norm), True


def configure_quest_gripper_actuators(
    model: Any,
    config: QuestGripperActuatorConfig | None = None,
) -> None:
    """Apply direct physical-finger actuator parameters to one M1 model instance."""

    cfg = config or QuestGripperActuatorConfig()
    values = (
        cfg.aperture_kp,
        cfg.aperture_kv,
        cfg.aperture_force_limit_n,
        cfg.finger_armature_kg,
        cfg.finger_damping_n_s_m,
        cfg.center_constraint_timeconst_s,
        cfg.center_constraint_damping_ratio,
    )
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        raise ValueError("Quest gripper actuator parameters must be finite and positive")
    for side in SIDES:
        actuator_id = model.actuator(f"{side}_gripper_aperture_position").id
        model.actuator_gainprm[actuator_id, 0] = cfg.aperture_kp
        # The passive q1+q2 tendon is orthogonal to aperture q1-q2, so it adds
        # no steady-state aperture bias.
        model.actuator_biasprm[actuator_id, 1] = -cfg.aperture_kp
        model.actuator_biasprm[actuator_id, 2] = -cfg.aperture_kv
        model.actuator_forcerange[actuator_id] = (
            -cfg.aperture_force_limit_n,
            cfg.aperture_force_limit_n,
        )
        center_constraint_id = model.equality(
            f"{side}_gripper_center_constraint"
        ).id
        model.eq_solref[center_constraint_id] = (
            cfg.center_constraint_timeconst_s,
            cfg.center_constraint_damping_ratio,
        )
        for follower in ("gripper_joint1", "gripper_joint2"):
            joint_id = model.joint(f"{side}_{follower}").id
            dof_id = int(model.jnt_dofadr[joint_id])
            model.dof_armature[dof_id] = cfg.finger_armature_kg
            model.dof_damping[dof_id] = cfg.finger_damping_n_s_m
            model.jnt_stiffness[joint_id] = 0.0


class PiperXMujocoQuestIkProcessor:
    """Use upstream PIPER-X IK, then emit bounded D0 degrees/millimetres.

    ``solvers`` must contain independent LeRobot ``RobotKinematics`` instances
    for left and right. The class deliberately depends only on their public
    ``forward_kinematics`` and ``inverse_kinematics`` methods.
    """

    def __init__(self, solvers: dict[str, Any], config: QuestIkConfig | None = None) -> None:
        if set(solvers) != set(SIDES):
            raise ValueError(f"solvers must contain exactly {SIDES}")
        self.solvers = solvers
        self.config = config or QuestIkConfig()
        self._target_d0: np.ndarray | None = None
        self._gripper_armed = {side: False for side in SIDES}
        self._validate_config()

    def _validate_config(self) -> None:
        cfg = self.config
        positive = (
            cfg.position_weight,
            cfg.max_translation_delta_m,
            cfg.max_rotation_delta_rad,
            cfg.rotation_activation_threshold_rad,
            cfg.max_joint_step_deg,
            cfg.max_joint_tracking_error_deg,
            cfg.max_gripper_step_mm,
            cfg.gripper_arm_open_threshold_mm,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in positive):
            raise ValueError("Quest IK position weight and bounds must be finite and positive")
        if not math.isfinite(cfg.orientation_weight) or cfg.orientation_weight < 0.0:
            raise ValueError("Quest IK orientation weight must be finite and non-negative")
        if not isinstance(cfg.controller_rotation_enabled, bool):
            raise ValueError("controller_rotation_enabled must be a boolean")
        if cfg.iterations_per_tick <= 0:
            raise ValueError("Quest IK iterations_per_tick must be positive")
        if not -1.0 <= cfg.minimum_translation_alignment <= 1.0:
            raise ValueError("minimum_translation_alignment must be within [-1, 1]")
        if cfg.gripper_arm_open_threshold_mm > 100.0:
            raise ValueError("gripper_arm_open_threshold_mm must not exceed 100")

    @staticmethod
    def _state(value: Iterable[float]) -> np.ndarray:
        state = np.asarray(value, dtype=np.float64)
        if state.shape != (14,) or not np.isfinite(state).all():
            raise ValueError("current D0 state must be one finite 14-element vector")
        return state.copy()

    def reset(self, current_d0_state: Iterable[float] | None = None) -> None:
        """Reset the persistent actuator target after an explicit scene reset."""

        self._target_d0 = None if current_d0_state is None else self._state(current_d0_state)
        self._gripper_armed = {side: False for side in SIDES}

    @property
    def target_d0(self) -> np.ndarray | None:
        return None if self._target_d0 is None else self._target_d0.copy()

    def action(self, current_d0_state: Iterable[float], command: Any) -> QuestIkResult:
        state = self._state(current_d0_state)
        if self._target_d0 is None or not command.session_active:
            self._target_d0 = state.copy()
        if not command.session_active:
            self._gripper_armed = {side: False for side in SIDES}

        output = self._target_d0.copy()
        saturation = np.zeros(14, dtype=np.bool_)
        cartesian_clipped = {side: False for side in SIDES}
        ik_failed = {side: False for side in SIDES}
        target_tracking_error = {side: 0.0 for side in SIDES}
        gripper_target_error = {side: 0.0 for side in SIDES}
        translation_alignment: dict[str, float | None] = {side: None for side in SIDES}
        achieved_translation_m = {side: [0.0, 0.0, 0.0] for side in SIDES}

        for side, offset, arm_command in zip(
            SIDES,
            (0, 7),
            (command.left, command.right),
            strict=True,
        ):
            current_joints = state[offset : offset + 6]
            target_joints = self._target_d0[offset : offset + 6]
            target_gripper_mm = float(self._target_d0[offset + 6])
            requested_gripper_mm = float(arm_command.gripper_aperture_m) * 1000.0
            if not command.session_active or not arm_command.tracking_valid or arm_command.rebased:
                self._gripper_armed[side] = False
                requested_gripper_mm = target_gripper_mm
            elif not self._gripper_armed[side]:
                if requested_gripper_mm >= self.config.gripper_arm_open_threshold_mm:
                    self._gripper_armed[side] = True
                # The release sample only arms the gripper. Applying it as a
                # command on the same frame would turn the safety edge itself
                # into an unexpected aperture change.
                requested_gripper_mm = target_gripper_mm
            bounded_gripper_mm = float(
                np.clip(
                    requested_gripper_mm,
                    target_gripper_mm - self.config.max_gripper_step_mm,
                    target_gripper_mm + self.config.max_gripper_step_mm,
                )
            )
            output[offset + 6] = bounded_gripper_mm
            saturation[offset + 6] = requested_gripper_mm != bounded_gripper_mm
            if (
                not command.session_active
                or not arm_command.tracking_valid
                or not arm_command.motion_active
                or arm_command.rebased
            ):
                continue

            delta = controller_delta_to_scene(arm_command.delta_pose)
            translation, clipped_position = _clip_vector_norm(
                delta[:3], self.config.max_translation_delta_m
            )
            rotation, clipped_rotation = _clip_vector_norm(
                delta[3:], self.config.max_rotation_delta_rad
            )
            rotation_requested = bool(
                np.linalg.norm(delta[3:]) >= self.config.rotation_activation_threshold_rad
            )
            rotation_ignored = bool(
                rotation_requested and not self.config.controller_rotation_enabled
            )
            if not self.config.controller_rotation_enabled or not rotation_requested:
                rotation = np.zeros(3, dtype=np.float64)
                clipped_rotation = False
            cartesian_clipped[side] = (
                clipped_position or clipped_rotation or rotation_ignored
            )

            solver = self.solvers[side]
            target = np.asarray(solver.forward_kinematics(target_joints), dtype=np.float64).copy()
            if target.shape != (4, 4) or not np.isfinite(target).all():
                ik_failed[side] = True
                continue
            target[:3, 3] += translation
            target[:3, :3] = _rotation_from_rotvec(rotation) @ target[:3, :3]

            solved = target_joints.copy()
            try:
                for _ in range(self.config.iterations_per_tick):
                    solved = np.asarray(
                        solver.inverse_kinematics(
                            solved,
                            target,
                            position_weight=self.config.position_weight,
                            orientation_weight=self.config.orientation_weight,
                        ),
                        dtype=np.float64,
                    )
            except (ArithmeticError, RuntimeError, ValueError):
                ik_failed[side] = True
                continue
            if solved.shape != (6,) or not np.isfinite(solved).all():
                ik_failed[side] = True
                continue

            def bound(solution: np.ndarray) -> np.ndarray:
                bounded_solution = np.clip(
                    solution,
                    target_joints - self.config.max_joint_step_deg,
                    target_joints + self.config.max_joint_step_deg,
                )
                bounded_solution = np.clip(
                    bounded_solution, JOINT_LIMITS_DEG[:, 0], JOINT_LIMITS_DEG[:, 1]
                )
                return np.clip(
                    bounded_solution,
                    current_joints - self.config.max_joint_tracking_error_deg,
                    current_joints + self.config.max_joint_tracking_error_deg,
                )

            def translation_result(solution: np.ndarray) -> tuple[np.ndarray, float | None]:
                reached = np.asarray(solver.forward_kinematics(solution), dtype=np.float64)
                achieved = reached[:3, 3] - (target[:3, 3] - translation)
                requested_norm = float(np.linalg.norm(translation))
                achieved_norm = float(np.linalg.norm(achieved))
                if requested_norm <= 1.0e-12:
                    return achieved, None
                if achieved_norm <= 1.0e-12:
                    return achieved, -1.0
                alignment = float(
                    np.dot(achieved, translation) / (achieved_norm * requested_norm)
                )
                return achieved, alignment

            bounded = bound(solved)
            try:
                achieved, alignment = translation_result(bounded)
                # If the coupled frame task turns a deliberate translation
                # sideways, retry the same upstream solver as position-only.
                # This is a narrow fallback, not a second IK implementation.
                if (
                    alignment is not None
                    and alignment < self.config.minimum_translation_alignment
                ):
                    position_only = target_joints.copy()
                    for _ in range(self.config.iterations_per_tick):
                        position_only = np.asarray(
                            solver.inverse_kinematics(
                                position_only,
                                target,
                                position_weight=self.config.position_weight,
                                orientation_weight=0.0,
                            ),
                            dtype=np.float64,
                        )
                    retry = bound(position_only)
                    retry_achieved, retry_alignment = translation_result(retry)
                    if retry_alignment is not None and retry_alignment > alignment:
                        bounded = retry
                        achieved = retry_achieved
                        alignment = retry_alignment
            except (ArithmeticError, RuntimeError, ValueError):
                ik_failed[side] = True
                continue
            if (
                alignment is not None
                and alignment < self.config.minimum_translation_alignment
            ):
                ik_failed[side] = True
                continue
            translation_alignment[side] = alignment
            achieved_translation_m[side] = achieved.tolist()
            saturation[offset : offset + 6] = solved != bounded
            output[offset : offset + 6] = bounded

        gripper_before = output[[6, 13]].copy()
        output[[6, 13]] = np.clip(output[[6, 13]], 0.0, 100.0)
        saturation[[6, 13]] |= gripper_before != output[[6, 13]]
        self._target_d0 = output.copy()
        for side, offset in (("left", 0), ("right", 7)):
            target_tracking_error[side] = float(
                np.max(np.abs(output[offset : offset + 6] - state[offset : offset + 6]))
            )
            gripper_target_error[side] = float(abs(output[offset + 6] - state[offset + 6]))
        return QuestIkResult(
            output,
            saturation,
            cartesian_clipped,
            ik_failed,
            target_tracking_error,
            gripper_target_error,
            self._gripper_armed.copy(),
            translation_alignment,
            achieved_translation_m,
        )
