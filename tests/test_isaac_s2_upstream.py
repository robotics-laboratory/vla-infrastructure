"""Pinned Candidate B tests for the narrow S2 relative-reference adapter."""

from __future__ import annotations

import importlib.metadata
import unittest

import numpy as np


class IsaacS2UpstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            version = importlib.metadata.version("isaacteleop")
            if version != "1.4.98rc1":
                raise unittest.SkipTest(
                    f"requires Candidate B isaacteleop 1.4.98rc1, found {version}"
                )
            from isaacteleop.retargeters import Se3RetargeterConfig
            from isaacteleop.retargeting_engine.deviceio_source_nodes import (
                ControllersSource,
            )
            from isaacteleop.retargeting_engine.interface.tensor_group import (
                OptionalTensorGroup,
            )
            from isaacteleop.retargeting_engine.tensor_types import (
                ControllerInputIndex,
            )
            from tools.isaac_s2_upstream import (
                ControllerButtonRetargeter,
                ControllerStateRetargeter,
                TrackingSafeSe3RelRetargeter,
            )
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"Candidate B teleop stack unavailable: {exc}") from exc

        cls.Se3RetargeterConfig = Se3RetargeterConfig
        cls.ControllersSource = ControllersSource
        cls.OptionalTensorGroup = OptionalTensorGroup
        cls.ControllerInputIndex = ControllerInputIndex
        cls.ControllerButtonRetargeter = ControllerButtonRetargeter
        cls.ControllerStateRetargeter = ControllerStateRetargeter
        cls.TrackingSafeSe3RelRetargeter = TrackingSafeSe3RelRetargeter

    def _controller(
        self,
        retargeter,
        position,
        *,
        valid=True,
        orientation=None,
        squeeze=0.0,
        trigger=0.0,
        sensitivity=0.0,
        secondary=0.0,
    ):
        group = self.OptionalTensorGroup(retargeter.input_spec()[self.ControllersSource.LEFT])
        group[self.ControllerInputIndex.GRIP_IS_VALID] = valid
        group[self.ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
        group[self.ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
            [0.0, 0.0, 0.0, 1.0] if orientation is None else orientation,
            dtype=np.float32,
        )
        group[self.ControllerInputIndex.SQUEEZE_VALUE] = squeeze
        group[self.ControllerInputIndex.TRIGGER_VALUE] = trigger
        group[self.ControllerInputIndex.THUMBSTICK_CLICK] = sensitivity
        group[self.ControllerInputIndex.SECONDARY_CLICK] = secondary
        return group

    def _delta(self, retargeter, group):
        result = retargeter({self.ControllersSource.LEFT: group})["ee_delta"][0]
        return np.asarray(result)

    def test_absence_clears_pose_baseline_and_smoothing_before_far_recovery(self) -> None:
        side = self.ControllersSource.LEFT
        retargeter = self.TrackingSafeSe3RelRetargeter(
            self.Se3RetargeterConfig(
                input_device=side,
                delta_pos_scale_factor=1.0,
                delta_rot_scale_factor=1.0,
            ),
            "tracking_safe_test",
        )
        np.testing.assert_array_equal(
            self._delta(retargeter, self._controller(retargeter, [0.0, 0.0, 0.0])),
            np.zeros(6),
        )
        np.testing.assert_allclose(
            self._delta(retargeter, self._controller(retargeter, [0.1, 0.0, 0.0])),
            [0.05, 0.0, 0.0, 0.0, 0.0, 0.0],
        )

        absent = self.OptionalTensorGroup(retargeter.input_spec()[side])
        np.testing.assert_array_equal(self._delta(retargeter, absent), np.zeros(6))
        np.testing.assert_array_equal(
            self._delta(retargeter, self._controller(retargeter, [50.0, -20.0, 8.0])),
            np.zeros(6),
        )
        np.testing.assert_allclose(
            self._delta(retargeter, self._controller(retargeter, [50.01, -20.0, 8.0])),
            [0.005, 0.0, 0.0, 0.0, 0.0, 0.0],
            atol=2.0e-6,
        )

    def test_invalid_and_default_pose_are_ignored_and_recovery_is_zero(self) -> None:
        side = self.ControllersSource.LEFT
        retargeter = self.TrackingSafeSe3RelRetargeter(
            self.Se3RetargeterConfig(input_device=side), "invalid_pose_test"
        )
        self._delta(retargeter, self._controller(retargeter, [1.0, 2.0, 3.0]))
        invalid = self._controller(
            retargeter,
            [-1.0e6, 1.0e6, -1.0e6],
            valid=False,
            orientation=[0.0, 0.0, 0.0, 0.0],
        )
        np.testing.assert_array_equal(self._delta(retargeter, invalid), np.zeros(6))
        default = self._controller(
            retargeter,
            [0.0, 0.0, 0.0],
            valid=True,
            orientation=[0.0, 0.0, 0.0, 0.0],
        )
        np.testing.assert_array_equal(self._delta(retargeter, default), np.zeros(6))
        recovered = self._controller(retargeter, [100.0, 100.0, 100.0])
        np.testing.assert_array_equal(self._delta(retargeter, recovered), np.zeros(6))

    def test_state_uses_thumbstick_click_and_effective_pose_validity(self) -> None:
        side = self.ControllersSource.LEFT
        retargeter = self.ControllerStateRetargeter(
            side, sensitivity_control="thumbstick_click", name="state_test"
        )
        controller = self._controller(
            retargeter,
            [0.1, 0.2, 0.3],
            squeeze=0.25,
            trigger=0.75,
            sensitivity=1.0,
        )
        state = np.asarray(retargeter({side: controller})["state"][0])
        np.testing.assert_allclose(state, [1.0, 1.0, 0.25, 0.75, 1.0])

        default = self._controller(
            retargeter,
            [0.0, 0.0, 0.0],
            valid=True,
            orientation=[0.0, 0.0, 0.0, 0.0],
        )
        state = np.asarray(retargeter({side: default})["state"][0])
        self.assertEqual(state[0], 1.0)
        self.assertEqual(state[1], 0.0)

    def test_demo_display_output_uses_free_left_secondary_button(self) -> None:
        side = self.ControllersSource.LEFT
        retargeter = self.ControllerButtonRetargeter(
            side, control="secondary_click", name="display_test"
        )
        controller = self._controller(
            retargeter,
            [0.1, 0.2, 0.3],
            squeeze=0.25,
            trigger=0.75,
            sensitivity=1.0,
            secondary=1.0,
        )
        value = np.asarray(retargeter({side: controller})["button"][0])
        np.testing.assert_array_equal(value, [1.0])


if __name__ == "__main__":
    unittest.main()
