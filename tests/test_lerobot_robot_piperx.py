"""Offline invariants for the PIPER-X LeRobot third-party plugin."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from lerobot.robots.utils import make_robot_from_config
from lerobot_robot_piperx.piperx import (
    BiPiperXFollower,
    BiPiperXFollowerConfig,
    PIPER_ACTION_KEYS,
    PIPER_JOINT_ACTION_KEYS,
    PiperXFollower,
    PiperXFollowerConfig,
    PiperXFollowerConfigBase,
)


EXPECTED_BIMANUAL_KEYS = tuple(f"left_{key}" for key in PIPER_ACTION_KEYS) + tuple(
    f"right_{key}" for key in PIPER_ACTION_KEYS
)


@dataclass
class FakeCameraConfig:
    height: int
    width: int
    fps: int = 30


class FakeCamera:
    def __init__(self, value: object):
        self.value = value
        self.is_connected = False
        self.connect_error: Exception | None = None
        self.disconnect_calls = 0
        self.latest_frame = value
        self.latest_timestamp = time.perf_counter()
        self.frame_lock = threading.Lock()
        self.new_frame_event = threading.Event()
        self.new_frame_event.set()

    def async_read(self) -> object:
        return self.value

    def connect(self) -> None:
        self.is_connected = True
        self.new_frame_event.set()
        if self.connect_error is not None:
            raise self.connect_error

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False


class FakeLogLevel:
    WARNING = object()


class FakePiper:
    instances: list[FakePiper] = []

    def __init__(self, **kwargs: object):
        self.kwargs = kwargs
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.enable_calls = 0
        self.disable_calls: list[int] = []
        self.master_slave_calls: list[tuple[int, int, int, int]] = []
        self.motion_control_calls: list[tuple[int, int, int, int]] = []
        self.connect_error: Exception | None = None
        self.disconnect_error: Exception | None = None
        self.enable_result = True
        self.joint_calls: list[tuple[int, ...]] = []
        self.gripper_calls: list[tuple[int, int, int, int]] = []
        self.joint_feedback = SimpleNamespace(
            joint_1=1001,
            joint_2=-2002,
            joint_3=3003,
            joint_4=-4004,
            joint_5=5005,
            joint_6=-6006,
        )
        self.gripper_feedback = SimpleNamespace(grippers_angle=-12345)
        self.joint_time_stamp = time.time()
        self.joint_hz = 30.0
        self.gripper_time_stamp = self.joint_time_stamp
        self.gripper_hz = 30.0
        FakePiper.instances.append(self)

    def ConnectPort(self) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error

    def DisconnectPort(self) -> None:
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error

    def EnablePiper(self) -> bool:
        self.enable_calls += 1
        return self.enable_result

    def DisableArm(self, motor: int) -> None:
        self.disable_calls.append(motor)

    def MasterSlaveConfig(self, *args: int) -> None:
        self.master_slave_calls.append(args)

    def MotionCtrl_2(self, *args: int) -> None:
        self.motion_control_calls.append(args)

    def JointCtrl(self, *commands: int) -> None:
        self.joint_calls.append(commands)

    def GripperCtrl(self, *commands: int) -> None:
        self.gripper_calls.append(commands)

    def GetArmJointMsgs(self) -> SimpleNamespace:
        return SimpleNamespace(
            time_stamp=self.joint_time_stamp,
            Hz=self.joint_hz,
            joint_state=self.joint_feedback,
        )

    def GetArmGripperMsgs(self) -> SimpleNamespace:
        return SimpleNamespace(
            time_stamp=self.gripper_time_stamp,
            Hz=self.gripper_hz,
            gripper_state=self.gripper_feedback,
        )


class PiperXPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        FakePiper.instances = []
        self.sdk_patch = patch(
            "lerobot_robot_piperx.piperx.get_piper_sdk", return_value=(FakePiper, FakeLogLevel)
        )
        self.can_patch = patch(
            "lerobot_robot_piperx.piperx.resolve_piper_can_interface", side_effect=lambda port: port
        )
        self.camera_patch = patch(
            "lerobot_robot_piperx.piperx.make_cameras_from_configs",
            side_effect=lambda configs: {key: FakeCamera(key) for key in configs},
        )
        self.sdk_patch.start()
        self.can_patch.start()
        self.camera_patch.start()
        self.addCleanup(self.sdk_patch.stop)
        self.addCleanup(self.can_patch.stop)
        self.addCleanup(self.camera_patch.stop)

    @staticmethod
    def follower_config(port: str = "fake-can") -> PiperXFollowerConfig:
        return PiperXFollowerConfig(port=port)

    @staticmethod
    def action(base: float = 1.0) -> dict[str, float]:
        return {key: base + index * 0.001 for index, key in enumerate(PIPER_JOINT_ACTION_KEYS)}

    @staticmethod
    def mark_connected(robot: PiperXFollower | BiPiperXFollower) -> None:
        if isinstance(robot, BiPiperXFollower):
            robot.left_arm._is_connected = True
            robot.left_arm._is_configured = True
            robot.left_arm._is_enabled = True
            robot.right_arm._is_connected = True
            robot.right_arm._is_configured = True
            robot.right_arm._is_enabled = True
            for arm in (robot.left_arm, robot.right_arm):
                for camera in arm.cameras.values():
                    camera.is_connected = True
        else:
            robot._is_connected = True
            robot._is_configured = True
            robot._is_enabled = True
            for camera in robot.cameras.values():
                camera.is_connected = True

    def test_plugin_discovery_registers_both_config_types(self) -> None:
        program = """
import importlib.metadata as metadata
from lerobot.robots.config import RobotConfig
from lerobot.utils.import_utils import register_third_party_plugins
assert any(d.metadata['Name'] == 'lerobot_robot_piperx' for d in metadata.distributions())
assert metadata.version('lerobot_robot_piperx') == '0.2.1'
register_third_party_plugins()
from lerobot_robot_piperx import BiPiperXFollowerConfig, PiperXFollowerConfig
assert PiperXFollowerConfig(port='offline').type == 'piperx_follower'
assert BiPiperXFollowerConfig(
    left_arm_config=__import__('lerobot_robot_piperx.piperx', fromlist=['PiperXFollowerConfigBase']).PiperXFollowerConfigBase(port='left'),
    right_arm_config=__import__('lerobot_robot_piperx.piperx', fromlist=['PiperXFollowerConfigBase']).PiperXFollowerConfigBase(port='right'),
).type == 'bi_piperx_follower'
"""
        result = subprocess.run(
            [sys.executable, "-c", program], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_factory_constructs_the_single_arm_robot_without_hardware(self) -> None:
        robot = make_robot_from_config(self.follower_config())
        self.assertIsInstance(robot, PiperXFollower)
        self.assertEqual(robot.robot_type, "piperx_follower")
        self.assertEqual(FakePiper.instances[0].kwargs["can_name"], "fake-can")

    def test_factory_constructs_the_bimanual_robot_without_hardware(self) -> None:
        config = BiPiperXFollowerConfig(
            id="pair",
            left_arm_config=PiperXFollowerConfigBase(port="left-can"),
            right_arm_config=PiperXFollowerConfigBase(port="right-can"),
        )
        robot = make_robot_from_config(config)
        self.assertIsInstance(robot, BiPiperXFollower)
        self.assertEqual(robot.robot_type, "bi_piperx_follower")
        self.assertEqual(
            [arm.kwargs["can_name"] for arm in FakePiper.instances], ["left-can", "right-can"]
        )

    def test_single_arm_feature_names_and_observation_order_are_exact(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.assertEqual(tuple(robot.action_features), PIPER_ACTION_KEYS)
        self.assertEqual(tuple(robot.observation_features), PIPER_ACTION_KEYS)
        self.assertEqual(len(robot.action_features), 7)

    def test_bimanual_scalar_features_are_exactly_14_and_left_then_right(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left"),
                right_arm_config=PiperXFollowerConfigBase(port="right"),
            )
        )
        self.assertEqual(tuple(robot.action_features), EXPECTED_BIMANUAL_KEYS)
        self.assertEqual(tuple(robot.observation_features), EXPECTED_BIMANUAL_KEYS)
        self.assertEqual(len(robot.action_features), 14)

    def test_configured_cameras_are_side_prefixed_in_features_and_observations(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(
                    port="left", cameras={"front": FakeCameraConfig(height=480, width=640)}
                ),
                right_arm_config=PiperXFollowerConfigBase(
                    port="right", cameras={"wrist": FakeCameraConfig(height=240, width=320)}
                ),
            )
        )
        self.mark_connected(robot)
        self.assertEqual(
            tuple(robot.observation_features),
            EXPECTED_BIMANUAL_KEYS + ("left_front", "right_wrist"),
        )
        self.assertEqual(robot.observation_features["left_front"], (480, 640, 3))
        self.assertEqual(robot.observation_features["right_wrist"], (240, 320, 3))
        self.assertEqual(robot.get_observation()["left_front"], "front")
        self.assertEqual(robot.get_observation()["right_wrist"], "wrist")

    def test_observation_uses_degree_conversion_and_absolute_gripper_travel(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        observation = robot.get_observation()
        self.assertEqual(tuple(observation), PIPER_ACTION_KEYS)
        self.assertAlmostEqual(observation["joint_1.pos"], 1.001)
        self.assertAlmostEqual(observation["joint_2.pos"], -2.002)
        self.assertAlmostEqual(observation["gripper.pos"], 12.345)

    def test_bimanual_recording_observation_exposes_common_monotonic_timing(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(
                    port="left",
                    cameras={"wrist": FakeCameraConfig(height=2, width=2)},
                    temporal_metadata=True,
                ),
                right_arm_config=PiperXFollowerConfigBase(
                    port="right",
                    cameras={"wrist": FakeCameraConfig(height=2, width=2)},
                    temporal_metadata=True,
                ),
            )
        )
        self.mark_connected(robot)
        robot.left_arm._calibrate_wall_to_monotonic()
        robot.right_arm._calibrate_wall_to_monotonic()

        robot.get_observation()
        timing = robot.latest_observation_timing()

        self.assertEqual(
            set(timing),
            {
                "observation.state",
                "observation.images.left_wrist",
                "observation.images.right_wrist",
            },
        )
        self.assertTrue(all(sample.sequence == 1 for sample in timing.values()))
        self.assertTrue(all(sample.clock_domain == "host_monotonic" for sample in timing.values()))

    def test_temporal_recording_rejects_missing_sdk_timestamp(self) -> None:
        robot = PiperXFollower(PiperXFollowerConfig(port="left", temporal_metadata=True))
        self.mark_connected(robot)
        robot._calibrate_wall_to_monotonic()
        FakePiper.instances[0].joint_time_stamp = 0.0

        with self.assertRaisesRegex(RuntimeError, "joint telemetry"):
            robot.get_observation()

    def test_missing_joint_telemetry_rejects_the_observation(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        del FakePiper.instances[0].joint_feedback.joint_4
        with self.assertRaisesRegex(RuntimeError, "joint_4"):
            robot.get_observation()

    def test_missing_gripper_telemetry_rejects_the_observation(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        FakePiper.instances[0].gripper_feedback = None
        with self.assertRaisesRegex(RuntimeError, "gripper telemetry"):
            robot.get_observation()

    def test_uninitialized_joint_envelope_rejects_sdk_synthetic_zeros(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        arm = FakePiper.instances[0]
        arm.joint_time_stamp = 0.0
        arm.joint_hz = 0.0
        for joint in arm.joint_feedback.__dict__:
            setattr(arm.joint_feedback, joint, 0)
        with self.assertRaisesRegex(RuntimeError, "joint telemetry"):
            robot.get_observation()

    def test_incomplete_joint_stream_rejects_zero_aggregate_rate(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        arm = FakePiper.instances[0]
        arm.joint_hz = 0.0
        with self.assertRaisesRegex(RuntimeError, "joint telemetry"):
            robot.get_observation()

    def test_uninitialized_gripper_envelope_rejects_sdk_synthetic_zero(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        arm = FakePiper.instances[0]
        arm.gripper_time_stamp = 0.0
        arm.gripper_hz = 0.0
        arm.gripper_feedback.grippers_angle = 0
        with self.assertRaisesRegex(RuntimeError, "gripper telemetry"):
            robot.get_observation()

    def test_connect_tracks_readiness_and_motion_requires_enabled_state(self) -> None:
        robot = PiperXFollower(
            PiperXFollowerConfig(port="fake-can", startup_sleep_s=0, enable_on_connect=False)
        )
        robot.connect()
        self.assertTrue(robot.is_connected)
        self.assertTrue(robot.is_configured)
        self.assertFalse(robot.is_enabled)
        self.assertFalse(robot.is_motion_ready)
        with self.assertRaisesRegex(RuntimeError, "motion is not ready"):
            robot.send_action(self.action())

        robot.enable()
        self.assertTrue(robot.is_enabled)
        self.assertTrue(robot.is_motion_ready)
        robot.send_action(self.action())
        self.assertEqual(len(FakePiper.instances[0].joint_calls), 1)
        robot.disconnect()
        self.assertFalse(robot.is_connected)
        self.assertFalse(robot.is_configured)
        self.assertFalse(robot.is_enabled)
        self.assertFalse(robot.is_motion_ready)

    def test_enable_timeout_fails_connect_and_rolls_back(self) -> None:
        robot = PiperXFollower(PiperXFollowerConfig(port="fake-can", startup_sleep_s=0))
        with patch("lerobot_robot_piperx.piperx.wait_enable_piper", return_value=False):
            with self.assertRaisesRegex(TimeoutError, "enabled state"):
                robot.connect()
        arm = FakePiper.instances[0]
        self.assertEqual(arm.disable_calls, [7])
        self.assertEqual(arm.disconnect_calls, 1)
        self.assertFalse(robot.is_connected)
        self.assertFalse(robot.is_motion_ready)

    def test_joint_and_gripper_commands_round_to_sdk_integers_and_return_sent_values(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        action = {
            "joint_1.pos": 1.2346,
            "joint_2.pos": -2.3456,
            "joint_3.pos": 3.4564,
            "joint_4.pos": -4.5674,
            "joint_5.pos": 5.6786,
            "joint_6.pos": -6.7896,
            "gripper.pos": -7.8906,
        }
        sent = robot.send_action(action)
        self.assertEqual(
            FakePiper.instances[0].joint_calls, [(1235, -2346, 3456, -4567, 5679, -6790)]
        )
        self.assertEqual(FakePiper.instances[0].gripper_calls, [(-7891, 1000, 1, 0)])
        self.assertEqual(
            sent,
            {
                "joint_1.pos": 1.235,
                "joint_2.pos": -2.346,
                "joint_3.pos": 3.456,
                "joint_4.pos": -4.567,
                "joint_5.pos": 5.679,
                "joint_6.pos": -6.79,
                "gripper.pos": -7.891,
            },
        )

    def test_partial_joints_reject_the_entire_action_before_gripper_motion(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        with self.assertRaisesRegex(ValueError, "Partial PIPER-X joint action rejected"):
            robot.send_action({"joint_1.pos": 9.0, "gripper.pos": 4.3214})
        self.assertEqual(FakePiper.instances[0].joint_calls, [])
        self.assertEqual(FakePiper.instances[0].gripper_calls, [])

    def test_no_project_added_clipping_or_slew_limit_is_applied(self) -> None:
        robot = PiperXFollower(self.follower_config())
        self.mark_connected(robot)
        first = {key: 10000.0006 for key in PIPER_JOINT_ACTION_KEYS} | {"gripper.pos": -9999.9996}
        second = {key: -10000.0006 for key in PIPER_JOINT_ACTION_KEYS} | {"gripper.pos": 9999.9996}
        robot.send_action(first)
        robot.send_action(second)
        arm = FakePiper.instances[0]
        self.assertEqual(arm.joint_calls, [(10000001,) * 6, (-10000001,) * 6])
        self.assertEqual(arm.gripper_calls, [(-10000000, 1000, 1, 0), (10000000, 1000, 1, 0)])

    def test_bimanual_routing_has_no_cross_talk_and_remains_process_local(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left"),
                right_arm_config=PiperXFollowerConfigBase(port="right"),
            )
        )
        self.mark_connected(robot)
        sent = robot.send_action(
            {f"left_{key}": value for key, value in self.action(1.0).items()}
            | {"left_gripper.pos": 2.0, "right_gripper.pos": -3.0}
        )
        left, right = FakePiper.instances
        self.assertIsInstance(robot.left_arm, PiperXFollower)
        self.assertIsInstance(robot.right_arm, PiperXFollower)
        self.assertEqual(left.joint_calls, [(1000, 1001, 1002, 1003, 1004, 1005)])
        self.assertEqual(right.joint_calls, [])
        self.assertEqual(left.gripper_calls, [(2000, 1000, 1, 0)])
        self.assertEqual(right.gripper_calls, [(-3000, 1000, 1, 0)])
        self.assertEqual(
            tuple(sent), tuple(f"left_{key}" for key in PIPER_ACTION_KEYS) + ("right_gripper.pos",)
        )

    def test_bimanual_prevalidates_both_arms_before_sending_either(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left"),
                right_arm_config=PiperXFollowerConfigBase(port="right"),
            )
        )
        self.mark_connected(robot)
        action = {f"left_{key}": value for key, value in self.action().items()}
        action["right_joint_1.pos"] = 2.0
        with self.assertRaisesRegex(ValueError, "Partial PIPER-X joint action rejected"):
            robot.send_action(action)
        left, right = FakePiper.instances
        self.assertEqual(left.joint_calls, [])
        self.assertEqual(right.joint_calls, [])

    def test_bimanual_preconverts_both_arms_before_sending_either(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left"),
                right_arm_config=PiperXFollowerConfigBase(port="right"),
            )
        )
        self.mark_connected(robot)
        action = {f"left_{key}": value for key, value in self.action().items()} | {
            f"right_{key}": value for key, value in self.action(2.0).items()
        }
        action["right_joint_6.pos"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            robot.send_action(action)
        left, right = FakePiper.instances
        self.assertEqual(left.joint_calls, [])
        self.assertEqual(right.joint_calls, [])

    def test_bimanual_connect_rolls_back_left_when_right_connect_fails(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left", startup_sleep_s=0),
                right_arm_config=PiperXFollowerConfigBase(port="right", startup_sleep_s=0),
            )
        )
        left, right = FakePiper.instances
        right.connect_error = RuntimeError("right connect failed")
        with self.assertRaisesRegex(RuntimeError, "right connect failed"):
            robot.connect()
        self.assertEqual(left.disconnect_calls, 1)
        self.assertEqual(left.disable_calls, [7])
        self.assertEqual(right.disconnect_calls, 1)
        self.assertFalse(robot.is_connected)
        self.assertFalse(robot.is_motion_ready)

    def test_connect_rolls_back_a_camera_that_raises_after_allocating(self) -> None:
        robot = PiperXFollower(
            PiperXFollowerConfig(
                port="fake-can",
                startup_sleep_s=0,
                cameras={"wrist": FakeCameraConfig(height=240, width=320)},
            )
        )
        camera = robot.cameras["wrist"]
        camera.connect_error = RuntimeError("camera connect failed after allocation")
        with self.assertRaisesRegex(RuntimeError, "camera connect failed"):
            robot.connect()
        self.assertFalse(camera.is_connected)
        self.assertEqual(camera.disconnect_calls, 1)
        self.assertEqual(FakePiper.instances[0].disconnect_calls, 1)
        self.assertFalse(robot.is_connected)

    def test_disconnect_cleans_arm_after_camera_drops(self) -> None:
        robot = PiperXFollower(
            PiperXFollowerConfig(
                port="fake-can",
                startup_sleep_s=0,
                cameras={"wrist": FakeCameraConfig(height=240, width=320)},
            )
        )
        robot.connect()
        robot.cameras["wrist"].is_connected = False
        self.assertFalse(robot.is_connected)
        robot.disconnect()
        self.assertEqual(FakePiper.instances[0].disconnect_calls, 1)
        self.assertFalse(robot._is_connected)

    def test_bimanual_disconnect_cleans_a_partially_connected_pair(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left", startup_sleep_s=0),
                right_arm_config=PiperXFollowerConfigBase(port="right", startup_sleep_s=0),
            )
        )
        robot.left_arm.connect()
        self.assertFalse(robot.is_connected)
        robot.disconnect()
        left, right = FakePiper.instances
        self.assertEqual(left.disconnect_calls, 1)
        self.assertEqual(right.disconnect_calls, 0)
        self.assertFalse(robot.left_arm._is_connected)

    def test_bimanual_disconnect_cleans_right_when_left_disconnect_fails(self) -> None:
        robot = BiPiperXFollower(
            BiPiperXFollowerConfig(
                left_arm_config=PiperXFollowerConfigBase(port="left", startup_sleep_s=0),
                right_arm_config=PiperXFollowerConfigBase(port="right", startup_sleep_s=0),
            )
        )
        robot.connect()
        left, right = FakePiper.instances
        left.disconnect_error = RuntimeError("left disconnect failed")
        with self.assertRaisesRegex(RuntimeError, "left disconnect failed"):
            robot.disconnect()
        self.assertEqual(left.disconnect_calls, 1)
        self.assertEqual(right.disconnect_calls, 1)
        self.assertFalse(robot.is_connected)
        self.assertFalse(robot.is_motion_ready)


if __name__ == "__main__":
    unittest.main()
