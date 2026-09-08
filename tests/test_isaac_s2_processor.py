"""Synthetic-pose checks for the concrete Gate S2 processor contract."""

from __future__ import annotations

import math
import unittest

import numpy as np

from tools.isaac_s2_processor import (
    BimanualS2TeleopProcessor,
    ControllerDeltaSample,
    S2ProcessorConfig,
    controller_pose_delta_xyzw,
    unpack_pipeline_action,
)


IDENTITY_POSE = np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])


def _quaternion(axis: int, angle: float) -> np.ndarray:
    quaternion = np.zeros(4)
    quaternion[axis] = math.sin(angle / 2.0)
    quaternion[3] = math.cos(angle / 2.0)
    return quaternion


def _sample(
    previous: np.ndarray = IDENTITY_POSE,
    current: np.ndarray = IDENTITY_POSE,
    *,
    available: bool = True,
    valid: bool = True,
    squeeze: float = 0.0,
    trigger: float = 0.0,
) -> ControllerDeltaSample:
    translation, rotation = controller_pose_delta_xyzw(previous, current)
    return ControllerDeltaSample(
        translation,
        rotation,
        available,
        valid,
        squeeze,
        trigger,
    )


class IsaacS2ProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.processor = BimanualS2TeleopProcessor()
        baseline = _sample()
        command = self.processor.advance(baseline, baseline)
        self.assertTrue(command.left.rebased)
        self.assertTrue(command.right.rebased)

    def test_left_and_right_routes_are_independent(self) -> None:
        left_pose = IDENTITY_POSE.copy()
        left_pose[0] = 0.01
        command = self.processor.advance(_sample(current=left_pose), _sample())
        np.testing.assert_allclose(command.left.delta_pose[:3], [0.1, 0.0, 0.0])
        np.testing.assert_allclose(command.right.delta_pose, np.zeros(6))

        right_pose = IDENTITY_POSE.copy()
        right_pose[1] = -0.02
        command = self.processor.advance(_sample(), _sample(current=right_pose))
        np.testing.assert_allclose(command.left.delta_pose, np.zeros(6))
        np.testing.assert_allclose(command.right.delta_pose[:3], [0.0, -0.2, 0.0])

    def test_all_translation_axes_and_signs_are_preserved_for_each_arm(self) -> None:
        for side in ("left", "right"):
            for axis in range(3):
                for sign in (-1.0, 1.0):
                    processor = BimanualS2TeleopProcessor()
                    processor.advance(_sample(), _sample())
                    pose = IDENTITY_POSE.copy()
                    pose[axis] = sign * 0.01
                    moved = _sample(current=pose)
                    command = processor.advance(
                        moved if side == "left" else _sample(),
                        moved if side == "right" else _sample(),
                    )
                    actual = getattr(command, side).delta_pose[:3]
                    expected = np.zeros(3)
                    expected[axis] = sign * 0.1
                    np.testing.assert_allclose(actual, expected, atol=1.0e-12)

    def test_xyzw_spatial_rotation_axes_and_scale(self) -> None:
        for side in ("left", "right"):
            for axis in range(3):
                for sign in (-1.0, 1.0):
                    processor = BimanualS2TeleopProcessor()
                    processor.advance(_sample(), _sample())
                    pose = IDENTITY_POSE.copy()
                    pose[3:] = _quaternion(axis, sign * 0.02)
                    moved = _sample(current=pose)
                    command = processor.advance(
                        moved if side == "left" else _sample(),
                        moved if side == "right" else _sample(),
                    )
                    expected = np.zeros(3)
                    expected[axis] = sign * 0.2
                    np.testing.assert_allclose(
                        getattr(command, side).delta_pose[3:], expected, atol=1.0e-12
                    )

    def test_scale_is_one_concrete_symmetric_configuration(self) -> None:
        config = S2ProcessorConfig()
        self.assertEqual(config.translation_scale, 10.0)
        self.assertEqual(config.rotation_scale, 10.0)
        command = self.processor.advance(
            ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0),
            ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0),
        )
        np.testing.assert_allclose(command.left.delta_pose, np.full(6, 10.0))
        np.testing.assert_allclose(command.right.delta_pose, np.full(6, 10.0))

    def test_clutch_freezes_and_release_rebases_independently(self) -> None:
        moving = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 1.0, 0.0)
        command = self.processor.advance(moving, _sample())
        self.assertEqual(command.left.transition, "clutch_engaged")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))

        command = self.processor.advance(moving, _sample())
        self.assertEqual(command.left.transition, "clutch_held")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))

        released = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0)
        command = self.processor.advance(released, _sample())
        self.assertEqual(command.left.transition, "clutch_release_rebased")
        self.assertTrue(command.left.rebased)
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertEqual(command.right.transition, "motion")

    def test_trigger_binary_gripper_mapping_is_independent(self) -> None:
        command = self.processor.advance(
            _sample(trigger=1.0),
            _sample(trigger=0.0),
        )
        self.assertEqual(command.left.gripper_aperture_m, 0.0)
        self.assertEqual(command.right.gripper_aperture_m, 0.1)
        command = self.processor.advance(
            _sample(trigger=0.0),
            _sample(trigger=1.0),
        )
        self.assertEqual(command.left.gripper_aperture_m, 0.1)
        self.assertEqual(command.right.gripper_aperture_m, 0.0)

    def test_tracking_invalid_holds_and_recovery_discards_first_delta(self) -> None:
        invalid = _sample(available=True, valid=False)
        command = self.processor.advance(invalid, _sample())
        self.assertEqual(command.left.transition, "tracking_lost")
        self.assertFalse(command.left.tracking_valid)
        self.assertEqual(command.right.transition, "motion")

        large = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0)
        command = self.processor.advance(large, _sample())
        self.assertEqual(command.left.transition, "tracking_rebased")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        command = self.processor.advance(large, _sample())
        np.testing.assert_allclose(command.left.delta_pose, np.full(6, 10.0))

    def test_unavailable_disconnect_and_reconnect_do_not_replay(self) -> None:
        inactive = self.processor.session_inactive()
        self.assertFalse(inactive.session_active)
        for arm in (inactive.left, inactive.right):
            np.testing.assert_array_equal(arm.delta_pose, np.zeros(6))

        large = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0)
        reconnected = self.processor.advance(large, large)
        self.assertTrue(reconnected.left.rebased)
        self.assertTrue(reconnected.right.rebased)
        np.testing.assert_array_equal(reconnected.left.delta_pose, np.zeros(6))
        np.testing.assert_array_equal(reconnected.right.delta_pose, np.zeros(6))

    def test_reset_clears_clutch_tracking_and_gripper_state(self) -> None:
        self.processor.advance(_sample(squeeze=1.0, trigger=1.0), _sample(trigger=1.0))
        self.processor.reset()
        command = self.processor.advance(_sample(), _sample())
        self.assertEqual(command.left.transition, "tracking_rebased")
        self.assertEqual(command.right.transition, "tracking_rebased")
        self.assertEqual(command.left.gripper_aperture_m, 0.1)
        self.assertEqual(command.right.gripper_aperture_m, 0.1)

    def test_fixed_upstream_action_layout(self) -> None:
        action = np.arange(20, dtype=np.float64)
        left, right = unpack_pipeline_action(action)
        np.testing.assert_array_equal(left.delta_position_m, [0.0, 1.0, 2.0])
        np.testing.assert_array_equal(left.delta_rotation_rotvec_rad, [3.0, 4.0, 5.0])
        self.assertTrue(left.available)
        self.assertEqual(left.trigger_value, 9.0)
        np.testing.assert_array_equal(right.delta_position_m, [10.0, 11.0, 12.0])
        np.testing.assert_array_equal(right.delta_rotation_rotvec_rad, [13.0, 14.0, 15.0])
        self.assertEqual(right.trigger_value, 19.0)


if __name__ == "__main__":
    unittest.main()
