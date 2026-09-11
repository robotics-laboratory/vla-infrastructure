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
    sensitivity: float = 0.0,
) -> ControllerDeltaSample:
    translation, rotation = controller_pose_delta_xyzw(previous, current)
    return ControllerDeltaSample(
        translation,
        rotation,
        available,
        valid,
        squeeze,
        trigger,
        sensitivity,
    )


class IsaacS2ProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.processor = BimanualS2TeleopProcessor()
        command = self.processor.advance(_sample(), _sample())
        self.assertTrue(command.left.rebased)
        self.assertTrue(command.right.rebased)

    def test_left_and_right_routes_are_independent(self) -> None:
        left_pose = IDENTITY_POSE.copy()
        left_pose[0] = 0.01
        command = self.processor.advance(_sample(current=left_pose), _sample())
        np.testing.assert_allclose(command.left.delta_pose[:3], [0.02, 0.0, 0.0])
        np.testing.assert_allclose(command.right.delta_pose, np.zeros(6))

        right_pose = IDENTITY_POSE.copy()
        right_pose[1] = -0.02
        command = self.processor.advance(_sample(), _sample(current=right_pose))
        np.testing.assert_allclose(command.left.delta_pose, np.zeros(6))
        np.testing.assert_allclose(command.right.delta_pose[:3], [0.0, -0.04, 0.0])

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
                    expected[axis] = sign * 0.02
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
                    expected[axis] = sign * 0.04
                    np.testing.assert_allclose(
                        getattr(command, side).delta_pose[3:], expected, atol=1.0e-12
                    )

    def test_normal_and_precise_gains_are_concrete_and_symmetric(self) -> None:
        config = S2ProcessorConfig()
        self.assertEqual(config.normal_translation_scale, 2.0)
        self.assertEqual(config.normal_rotation_scale, 2.0)
        self.assertEqual(config.precise_translation_scale, 0.5)
        self.assertEqual(config.precise_rotation_scale, 0.5)
        sample = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
        command = self.processor.advance(sample, sample)
        np.testing.assert_allclose(command.left.delta_pose, np.full(6, 2.0))
        np.testing.assert_allclose(command.right.delta_pose, np.full(6, 2.0))

    def test_sensitivity_switch_is_independent_debounced_and_has_no_jump(self) -> None:
        delta = ControllerDeltaSample(np.full(3, 0.01), np.full(3, 0.02), True, True, 0.0, 0.0, 1.0)
        right_motion = ControllerDeltaSample(
            np.full(3, 0.01), np.zeros(3), True, True, 0.0, 0.0, 0.0
        )
        command = self.processor.advance(delta, right_motion)
        self.assertEqual(command.left.transition, "sensitivity_switched_precise")
        self.assertEqual(command.left.sensitivity_mode, "precise")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertEqual(command.right.sensitivity_mode, "normal")
        np.testing.assert_allclose(command.right.delta_pose[:3], np.full(3, 0.02))

        command = self.processor.advance(delta, right_motion)
        np.testing.assert_allclose(command.left.delta_pose, [0.005, 0.005, 0.005, 0.01, 0.01, 0.01])
        self.assertEqual(command.left.sensitivity_mode, "precise")

        self.processor.advance(_sample(sensitivity=0.0), _sample())
        command = self.processor.advance(delta, _sample())
        self.assertEqual(command.left.transition, "sensitivity_switched_normal")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertEqual(command.left.sensitivity_mode, "normal")

    def test_demo_candidate_gains_and_shared_y_edges_switch_both_without_jump(self) -> None:
        processor = BimanualS2TeleopProcessor(
            S2ProcessorConfig(
                normal_translation_scale=4.0,
                normal_rotation_scale=4.0,
                precise_translation_scale=1.0,
                precise_rotation_scale=1.0,
            )
        )
        processor.advance(_sample(), _sample())
        motion = ControllerDeltaSample(
            np.full(3, 0.01), np.full(3, 0.02), True, True, 0.0, 0.5, 0.0
        )
        command = processor.advance(motion, motion)
        np.testing.assert_allclose(command.left.delta_pose, [0.04] * 3 + [0.08] * 3)
        np.testing.assert_allclose(command.right.delta_pose, [0.04] * 3 + [0.08] * 3)

        pressed = ControllerDeltaSample(
            np.full(3, 0.01), np.full(3, 0.02), True, True, 0.0, 0.5, 1.0
        )
        command = processor.advance(pressed, pressed)
        self.assertEqual(command.left.sensitivity_mode, "precise")
        self.assertEqual(command.right.sensitivity_mode, "precise")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        np.testing.assert_array_equal(command.right.delta_pose, np.zeros(6))

        # A held physical button is a state, not a stream of toggle commands.
        for _ in range(5):
            command = processor.advance(pressed, pressed)
            self.assertEqual(command.left.sensitivity_mode, "precise")
            self.assertEqual(command.right.sensitivity_mode, "precise")
            np.testing.assert_allclose(command.left.delta_pose, [0.01] * 3 + [0.02] * 3)
            np.testing.assert_allclose(command.right.delta_pose, [0.01] * 3 + [0.02] * 3)

        for _ in range(3):
            processor.advance(motion, motion)
            command = processor.advance(pressed, pressed)
            self.assertEqual(command.left.sensitivity_mode, "normal")
            self.assertEqual(command.right.sensitivity_mode, "normal")
            np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
            np.testing.assert_array_equal(command.right.delta_pose, np.zeros(6))
            processor.advance(motion, motion)
            command = processor.advance(pressed, pressed)
            self.assertEqual(command.left.sensitivity_mode, "precise")
            self.assertEqual(command.right.sensitivity_mode, "precise")
            np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
            np.testing.assert_array_equal(command.right.delta_pose, np.zeros(6))

    def test_clutch_freezes_and_release_rebases_independently(self) -> None:
        moving = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 1.0, 0.0, 0.0)
        command = self.processor.advance(moving, _sample())
        self.assertEqual(command.left.transition, "clutch_engaged")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        command = self.processor.advance(moving, _sample())
        self.assertEqual(command.left.transition, "clutch_held")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))

        released = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
        command = self.processor.advance(released, _sample())
        self.assertEqual(command.left.transition, "clutch_release_rebased")
        self.assertTrue(command.left.rebased)
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertEqual(command.right.transition, "motion")

    def test_trigger_is_analog_at_required_points_and_independent(self) -> None:
        for trigger, expected_aperture in (
            (0.0, 0.1),
            (0.25, 0.075),
            (0.5, 0.05),
            (0.75, 0.025),
            (1.0, 0.0),
        ):
            command = self.processor.advance(
                _sample(trigger=trigger), _sample(trigger=1.0 - trigger)
            )
            self.assertAlmostEqual(command.left.gripper_aperture_m, expected_aperture)
            self.assertAlmostEqual(command.right.gripper_aperture_m, 0.1 - expected_aperture)

    def test_tracking_loss_invalid_poses_and_far_recovery_emit_no_jump(self) -> None:
        before_loss = ControllerDeltaSample(
            np.full(3, 0.01), np.zeros(3), True, True, 0.0, 0.0, 0.0
        )
        self.processor.advance(before_loss, _sample())

        arbitrary_invalid = ControllerDeltaSample(
            np.full(3, -1.0e6),
            np.full(3, 1.0e6),
            True,
            False,
            1.0,
            1.0,
            1.0,
        )
        command = self.processor.advance(arbitrary_invalid, _sample())
        self.assertEqual(command.left.transition, "tracking_lost")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertEqual(command.right.transition, "motion")

        unavailable = ControllerDeltaSample(
            np.full(3, 9.0e8),
            np.full(3, -9.0e8),
            False,
            False,
            0.0,
            0.0,
            0.0,
        )
        command = self.processor.advance(unavailable, _sample())
        self.assertEqual(command.left.transition, "tracking_invalid")
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))

        far_recovered = ControllerDeltaSample(
            np.full(3, 100.0), np.full(3, -3.0), True, True, 0.0, 0.0, 0.0
        )
        command = self.processor.advance(far_recovered, _sample())
        self.assertEqual(command.left.transition, "tracking_rebased")
        self.assertTrue(command.left.rebased)
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))

        next_delta = ControllerDeltaSample(
            np.asarray([0.01, 0.0, 0.0]),
            np.zeros(3),
            True,
            True,
            0.0,
            0.0,
            0.0,
        )
        command = self.processor.advance(next_delta, _sample())
        np.testing.assert_allclose(command.left.delta_pose[:3], [0.02, 0.0, 0.0])

    def test_independent_loss_does_not_disable_opposite_controller(self) -> None:
        invalid = _sample(available=True, valid=False)
        right_pose = IDENTITY_POSE.copy()
        right_pose[2] = 0.02
        command = self.processor.advance(invalid, _sample(current=right_pose))
        self.assertFalse(command.left.tracking_valid)
        np.testing.assert_array_equal(command.left.delta_pose, np.zeros(6))
        self.assertTrue(command.right.tracking_valid)
        np.testing.assert_allclose(command.right.delta_pose[:3], [0.0, 0.0, 0.04])

    def test_unavailable_disconnect_and_reconnect_do_not_replay(self) -> None:
        inactive = self.processor.session_inactive()
        self.assertFalse(inactive.session_active)
        for arm in (inactive.left, inactive.right):
            np.testing.assert_array_equal(arm.delta_pose, np.zeros(6))

        large = ControllerDeltaSample(np.ones(3), np.ones(3), True, True, 0.0, 0.0, 0.0)
        reconnected = self.processor.advance(large, large)
        self.assertTrue(reconnected.left.rebased)
        self.assertTrue(reconnected.right.rebased)
        np.testing.assert_array_equal(reconnected.left.delta_pose, np.zeros(6))
        np.testing.assert_array_equal(reconnected.right.delta_pose, np.zeros(6))

    def test_reset_clears_clutch_tracking_gripper_and_sensitivity(self) -> None:
        self.processor.advance(
            _sample(squeeze=1.0, trigger=1.0, sensitivity=1.0),
            _sample(trigger=1.0),
        )
        self.processor.reset()
        command = self.processor.advance(_sample(), _sample())
        self.assertEqual(command.left.transition, "tracking_rebased")
        self.assertEqual(command.right.transition, "tracking_rebased")
        self.assertEqual(command.left.gripper_aperture_m, 0.1)
        self.assertEqual(command.right.gripper_aperture_m, 0.1)
        self.assertEqual(command.left.sensitivity_mode, "normal")
        self.assertEqual(command.right.sensitivity_mode, "normal")

    def test_fixed_upstream_action_layout(self) -> None:
        action = np.arange(22, dtype=np.float64)
        left, right = unpack_pipeline_action(action)
        np.testing.assert_array_equal(left.delta_position_m, [0.0, 1.0, 2.0])
        np.testing.assert_array_equal(left.delta_rotation_rotvec_rad, [3.0, 4.0, 5.0])
        self.assertTrue(left.available)
        self.assertEqual(left.trigger_value, 9.0)
        self.assertEqual(left.sensitivity_button_value, 10.0)
        np.testing.assert_array_equal(right.delta_position_m, [11.0, 12.0, 13.0])
        np.testing.assert_array_equal(right.delta_rotation_rotvec_rad, [14.0, 15.0, 16.0])
        self.assertEqual(right.trigger_value, 20.0)
        self.assertEqual(right.sensitivity_button_value, 21.0)


if __name__ == "__main__":
    unittest.main()
