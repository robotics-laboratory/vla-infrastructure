"""PIPER-X Robot implementations adapted from the pinned Evo-RL Robot-side donor."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from lerobot.cameras import CameraConfig, make_cameras_from_configs
from lerobot.lerobot_types import RobotAction, RobotObservation
from lerobot.robots.config import RobotConfig
from lerobot.robots.robot import Robot
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected
from lerobot.utils.errors import DeviceNotConnectedError

from .sdk import (
    PIPER_ACTION_KEYS,
    PIPER_JOINT_ACTION_KEYS,
    PIPER_JOINT_NAMES,
    PIPER_ROLE_FOLLOWER,
    get_piper_sdk,
    milli_to_unit,
    parse_piper_log_level,
    resolve_piper_can_interface,
    unit_to_milli,
    wait_enable_piper,
)


@dataclass(kw_only=True)
class PiperXFollowerConfigBase:
    """PIPER-X follower connection and motion-mode settings."""

    port: str
    judge_flag: bool = False
    can_auto_init: bool = True
    log_level: str = "WARNING"
    startup_sleep_s: float = 0.1
    speed_ratio: int = 100
    high_follow: bool = True
    enable_on_connect: bool = True
    enable_timeout_s: float = 3.0
    sync_gripper: bool = True
    gripper_effort_default: int = 1000
    gripper_status_code: int = 0x01
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    disable_on_disconnect: bool = False


@RobotConfig.register_subclass("piperx_follower")
@dataclass(kw_only=True)
class PiperXFollowerConfig(RobotConfig, PiperXFollowerConfigBase):
    pass


@RobotConfig.register_subclass("bi_piperx_follower")
@dataclass(kw_only=True)
class BiPiperXFollowerConfig(RobotConfig):
    left_arm_config: PiperXFollowerConfigBase
    right_arm_config: PiperXFollowerConfigBase


class PiperXFollower(Robot):
    """A PIPER-X follower using the pinned SDK's J-position command path."""

    config_class = PiperXFollowerConfig
    name = "piperx_follower"

    def __init__(self, config: PiperXFollowerConfig):
        self.robot_type = self.name
        self.id = config.id
        self.config = config
        self._is_connected = False
        self._is_configured = False
        self._is_enabled = False
        interface_cls, _ = get_piper_sdk()
        self.arm = interface_cls(
            can_name=resolve_piper_can_interface(config.port),
            judge_flag=config.judge_flag,
            can_auto_init=config.can_auto_init,
            logger_level=parse_piper_log_level(config.log_level),
        )
        self.cameras = make_cameras_from_configs(config.cameras)

    @property
    def _motors_ft(self) -> dict[str, type[float]]:
        return dict.fromkeys(PIPER_ACTION_KEYS, float)

    @property
    def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
        return {
            key: (self.config.cameras[key].height, self.config.cameras[key].width, 3)
            for key in self.cameras
        }

    @cached_property
    def observation_features(self) -> dict[str, type[float] | tuple[int, int, int]]:
        return {**self._motors_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type[float]]:
        return self._motors_ft

    @property
    def is_connected(self) -> bool:
        return self._is_connected and all(camera.is_connected for camera in self.cameras.values())

    @property
    def is_configured(self) -> bool:
        return self._is_connected and self._is_configured

    @property
    def is_enabled(self) -> bool:
        return self.is_configured and self._is_enabled

    @property
    def is_motion_ready(self) -> bool:
        return self.is_connected and self.is_configured and self.is_enabled

    def _cleanup_connection(self, cameras: list[Any], *, force_disable: bool) -> list[Exception]:
        errors: list[Exception] = []
        if force_disable or self.config.disable_on_disconnect:
            try:
                self.arm.DisableArm(7)
            except Exception as exc:
                errors.append(exc)
        try:
            self.arm.DisconnectPort()
        except Exception as exc:
            errors.append(exc)
        for camera in reversed(cameras):
            try:
                camera.disconnect()
            except Exception as exc:
                errors.append(exc)
        self._is_enabled = False
        self._is_configured = False
        self._is_connected = False
        return errors

    @staticmethod
    def _raise_cleanup_errors(errors: list[Exception]) -> None:
        if not errors:
            return
        first, *remaining = errors
        for error in remaining:
            first.add_note(f"Additional cleanup failure: {error!r}")
        raise first

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        connected_cameras: list[Any] = []
        enable_attempted = False
        try:
            self.arm.ConnectPort()
            self._is_connected = True
            if self.config.startup_sleep_s > 0:
                time.sleep(self.config.startup_sleep_s)
            self.configure()
            if self.config.enable_on_connect:
                enable_attempted = True
                self.enable()
            for camera in self.cameras.values():
                connected_cameras.append(camera)
                camera.connect()
        except Exception as exc:
            cleanup_errors = self._cleanup_connection(
                connected_cameras, force_disable=enable_attempted
            )
            for error in cleanup_errors:
                exc.add_note(f"Connect rollback failure: {error!r}")
            raise

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        if not self._is_connected:
            raise RuntimeError("Cannot configure PIPER-X before the CAN connection is established.")
        self._is_configured = False
        self._is_enabled = False
        self.arm.MasterSlaveConfig(PIPER_ROLE_FOLLOWER, 0x00, 0x00, 0x00)
        self.arm.MotionCtrl_2(
            0x01, 0x01, self.config.speed_ratio, 0xAD if self.config.high_follow else 0x00
        )
        self._is_configured = True

    def enable(self) -> None:
        if not self.is_configured:
            raise RuntimeError("Cannot enable PIPER-X before it is connected and configured.")
        self._is_enabled = False
        if not wait_enable_piper(self.arm, self.config.enable_timeout_s):
            raise TimeoutError("PIPER-X follower did not report enabled state before timeout.")
        self._is_enabled = True

    @staticmethod
    def _telemetry_value(payload: Any, field_name: str, source_name: str) -> float | int:
        value = getattr(payload, field_name, None)
        if value is None:
            raise RuntimeError(
                f"Missing required PIPER-X {source_name} telemetry field '{field_name}'."
            )
        return value

    @staticmethod
    def _telemetry_payload(envelope: Any, field_name: str, source_name: str) -> Any:
        timestamp = getattr(envelope, "time_stamp", None)
        rate_hz = getattr(envelope, "Hz", None)
        if timestamp is None or rate_hz is None:
            valid_envelope = False
        else:
            try:
                valid_envelope = (
                    math.isfinite(float(timestamp))
                    and float(timestamp) > 0
                    and math.isfinite(float(rate_hz))
                    and float(rate_hz) > 0
                )
            except (TypeError, ValueError, OverflowError):
                valid_envelope = False
        if not valid_envelope:
            raise RuntimeError(
                f"Missing or incomplete PIPER-X {source_name} telemetry; "
                "the SDK envelope requires positive finite time_stamp and Hz values."
            )
        payload = getattr(envelope, field_name, None)
        if payload is None:
            raise RuntimeError(
                f"Missing required PIPER-X {source_name} telemetry payload '{field_name}'."
            )
        return payload

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        joint_state = self._telemetry_payload(self.arm.GetArmJointMsgs(), "joint_state", "joint")
        observation: RobotObservation = {
            f"{joint}.pos": milli_to_unit(self._telemetry_value(joint_state, joint, "joint"))
            for joint in PIPER_JOINT_NAMES
        }
        gripper_state = self._telemetry_payload(
            self.arm.GetArmGripperMsgs(), "gripper_state", "gripper"
        )
        observation["gripper.pos"] = abs(
            milli_to_unit(self._telemetry_value(gripper_state, "grippers_angle", "gripper"))
        )
        observation.update({key: camera.async_read() for key, camera in self.cameras.items()})
        return observation

    def _validate_action(self, action: RobotAction) -> None:
        if not self.is_motion_ready:
            raise RuntimeError(
                "PIPER-X motion is not ready; connected, configured, and enabled states are required."
            )
        present_joint_keys = [key for key in PIPER_JOINT_ACTION_KEYS if key in action]
        if present_joint_keys and len(present_joint_keys) != len(PIPER_JOINT_ACTION_KEYS):
            missing = [key for key in PIPER_JOINT_ACTION_KEYS if key not in action]
            raise ValueError(
                "Partial PIPER-X joint action rejected; all six joint keys are required. "
                f"Missing: {missing}"
            )

    def _prepare_action(self, action: RobotAction) -> tuple[tuple[int, ...] | None, int | None]:
        """Validate and convert every command before any SDK motion call."""
        self._validate_action(action)
        try:
            joint_commands = (
                tuple(unit_to_milli(action[key]) for key in PIPER_JOINT_ACTION_KEYS)
                if all(key in action for key in PIPER_JOINT_ACTION_KEYS)
                else None
            )
            gripper_command = (
                unit_to_milli(action["gripper.pos"])
                if self.config.sync_gripper and "gripper.pos" in action
                else None
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("PIPER-X action values must be finite numeric values.") from exc
        return joint_commands, gripper_command

    def _send_prepared_action(
        self, joint_commands: tuple[int, ...] | None, gripper_command: int | None
    ) -> RobotAction:
        sent_action: RobotAction = {}
        if joint_commands is not None:
            self.arm.JointCtrl(*joint_commands)
            sent_action.update(
                {
                    key: milli_to_unit(raw)
                    for key, raw in zip(PIPER_JOINT_ACTION_KEYS, joint_commands, strict=True)
                }
            )
        if gripper_command is not None:
            self.arm.GripperCtrl(
                gripper_command,
                self.config.gripper_effort_default,
                self.config.gripper_status_code,
                0x00,
            )
            sent_action["gripper.pos"] = milli_to_unit(gripper_command)
        return sent_action

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        return self._send_prepared_action(*self._prepare_action(action))

    def disconnect(self) -> None:
        if not self._has_connection_resources:
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__} is not connected. Run `.connect()` first."
            )
        errors = self._cleanup_connection(list(self.cameras.values()), force_disable=False)
        self._raise_cleanup_errors(errors)

    @property
    def _has_connection_resources(self) -> bool:
        return (
            self._is_connected
            or self._is_configured
            or self._is_enabled
            or any(camera.is_connected for camera in self.cameras.values())
        )


class BiPiperXFollower(Robot):
    """Process-local left/right composition of two PIPER-X followers."""

    config_class = BiPiperXFollowerConfig
    name = "bi_piperx_follower"
    _arm_fields = tuple(PiperXFollowerConfigBase.__dataclass_fields__)

    def __init__(self, config: BiPiperXFollowerConfig):
        self.robot_type = self.name
        self.id = config.id
        self.config = config
        self.left_arm = PiperXFollower(self._arm_config(config.left_arm_config, "left"))
        self.right_arm = PiperXFollower(self._arm_config(config.right_arm_config, "right"))
        self.cameras = {**self.left_arm.cameras, **self.right_arm.cameras}

    def _arm_config(self, side_config: PiperXFollowerConfigBase, side: str) -> PiperXFollowerConfig:
        kwargs = {name: getattr(side_config, name) for name in self._arm_fields}
        kwargs["id"] = f"{self.id}_{side}" if self.id else None
        return PiperXFollowerConfig(**kwargs)

    @property
    def _motors_ft(self) -> dict[str, type[float]]:
        return {
            **{f"left_{key}": value for key, value in self.left_arm._motors_ft.items()},
            **{f"right_{key}": value for key, value in self.right_arm._motors_ft.items()},
        }

    @property
    def _cameras_ft(self) -> dict[str, tuple[int, int, int]]:
        return {
            **{f"left_{key}": value for key, value in self.left_arm._cameras_ft.items()},
            **{f"right_{key}": value for key, value in self.right_arm._cameras_ft.items()},
        }

    @cached_property
    def observation_features(self) -> dict[str, type[float] | tuple[int, int, int]]:
        return {**self._motors_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type[float]]:
        return self._motors_ft

    @property
    def is_connected(self) -> bool:
        return self.left_arm.is_connected and self.right_arm.is_connected

    @property
    def is_configured(self) -> bool:
        return self.left_arm.is_configured and self.right_arm.is_configured

    @property
    def is_enabled(self) -> bool:
        return self.left_arm.is_enabled and self.right_arm.is_enabled

    @property
    def is_motion_ready(self) -> bool:
        return self.left_arm.is_motion_ready and self.right_arm.is_motion_ready

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        connected_arms: list[PiperXFollower] = []
        try:
            self.left_arm.connect()
            connected_arms.append(self.left_arm)
            self.right_arm.connect()
            connected_arms.append(self.right_arm)
        except Exception as exc:
            for arm in reversed(connected_arms):
                cleanup_errors = arm._cleanup_connection(
                    list(arm.cameras.values()), force_disable=True
                )
                for cleanup_exc in cleanup_errors:
                    exc.add_note(f"Bimanual connect rollback failure: {cleanup_exc!r}")
            raise

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        self.left_arm.configure()
        self.right_arm.configure()

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        return {
            **{f"left_{key}": value for key, value in self.left_arm.get_observation().items()},
            **{f"right_{key}": value for key, value in self.right_arm.get_observation().items()},
        }

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        if not self.is_motion_ready:
            raise RuntimeError(
                "Bimanual PIPER-X motion is not ready; both arms must be connected, configured, and enabled."
            )
        left_action = {
            key.removeprefix("left_"): value
            for key, value in action.items()
            if key.startswith("left_")
        }
        right_action = {
            key.removeprefix("right_"): value
            for key, value in action.items()
            if key.startswith("right_")
        }
        left_prepared = self.left_arm._prepare_action(left_action)
        right_prepared = self.right_arm._prepare_action(right_action)
        return {
            **{
                f"left_{key}": value
                for key, value in self.left_arm._send_prepared_action(*left_prepared).items()
            },
            **{
                f"right_{key}": value
                for key, value in self.right_arm._send_prepared_action(*right_prepared).items()
            },
        }

    def disconnect(self) -> None:
        if not any(arm._has_connection_resources for arm in (self.left_arm, self.right_arm)):
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__} is not connected. Run `.connect()` first."
            )
        errors: list[Exception] = []
        for arm in (self.left_arm, self.right_arm):
            if not arm._has_connection_resources:
                continue
            try:
                arm.disconnect()
            except Exception as exc:
                errors.append(exc)
        PiperXFollower._raise_cleanup_errors(errors)
