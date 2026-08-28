"""PIPER-X Robot implementations adapted from the pinned Evo-RL Robot-side donor."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from lerobot.cameras import CameraConfig, make_cameras_from_configs
from lerobot.lerobot_types import RobotAction, RobotObservation
from lerobot.robots.config import RobotConfig
from lerobot.robots.robot import Robot
from lerobot.utils.decorators import check_if_already_connected, check_if_not_connected

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

logger = logging.getLogger(__name__)


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

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        self.arm.ConnectPort()
        connected_cameras: list[Any] = []
        try:
            if self.config.startup_sleep_s > 0:
                time.sleep(self.config.startup_sleep_s)
            self._is_connected = True
            self.configure()
            if self.config.enable_on_connect and not wait_enable_piper(self.arm, self.config.enable_timeout_s):
                logger.warning("PIPER-X follower did not report enabled state before timeout.")
            for camera in self.cameras.values():
                camera.connect()
                connected_cameras.append(camera)
        except Exception:
            self.arm.DisconnectPort()
            for camera in connected_cameras:
                camera.disconnect()
            self._is_connected = False
            raise

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        pass

    def configure(self) -> None:
        self.arm.MasterSlaveConfig(PIPER_ROLE_FOLLOWER, 0x00, 0x00, 0x00)
        self.arm.MotionCtrl_2(0x01, 0x01, self.config.speed_ratio, 0xAD if self.config.high_follow else 0x00)

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        joint_state = getattr(self.arm.GetArmJointMsgs(), "joint_state", None)
        observation: RobotObservation = {
            f"{joint}.pos": milli_to_unit(getattr(joint_state, joint, 0)) for joint in PIPER_JOINT_NAMES
        }
        gripper_state = getattr(self.arm.GetArmGripperMsgs(), "gripper_state", None)
        observation["gripper.pos"] = abs(milli_to_unit(getattr(gripper_state, "grippers_angle", 0)))
        observation.update({key: camera.async_read() for key, camera in self.cameras.items()})
        return observation

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        sent_action: RobotAction = {}
        if all(key in action for key in PIPER_JOINT_ACTION_KEYS):
            commands = [unit_to_milli(action[key]) for key in PIPER_JOINT_ACTION_KEYS]
            self.arm.JointCtrl(*commands)
            sent_action.update(
                {
                    key: milli_to_unit(raw)
                    for key, raw in zip(PIPER_JOINT_ACTION_KEYS, commands, strict=True)
                }
            )
        elif any(key in action for key in PIPER_JOINT_ACTION_KEYS):
            logger.debug("Ignoring partial PIPER-X joint action; all six joint keys are required.")
        if self.config.sync_gripper and "gripper.pos" in action:
            command = unit_to_milli(action["gripper.pos"])
            self.arm.GripperCtrl(
                command,
                self.config.gripper_effort_default,
                self.config.gripper_status_code,
                0x00,
            )
            sent_action["gripper.pos"] = milli_to_unit(command)
        return sent_action

    @check_if_not_connected
    def disconnect(self) -> None:
        try:
            if self.config.disable_on_disconnect:
                self.arm.DisableArm(7)
        finally:
            self.arm.DisconnectPort()
            for camera in self.cameras.values():
                camera.disconnect()
            self._is_connected = False


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

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        del calibrate
        self.left_arm.connect()
        self.right_arm.connect()

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
        left_action = {key.removeprefix("left_"): value for key, value in action.items() if key.startswith("left_")}
        right_action = {
            key.removeprefix("right_"): value for key, value in action.items() if key.startswith("right_")
        }
        return {
            **{f"left_{key}": value for key, value in self.left_arm.send_action(left_action).items()},
            **{f"right_{key}": value for key, value in self.right_arm.send_action(right_action).items()},
        }

    @check_if_not_connected
    def disconnect(self) -> None:
        self.left_arm.disconnect()
        self.right_arm.disconnect()
