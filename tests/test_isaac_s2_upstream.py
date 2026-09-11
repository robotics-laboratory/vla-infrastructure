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
                build_piper_x_bimanual_pipeline,
            )
            from tools.isaac_robosyn_vr_demo import DemoRuntime
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"Candidate B teleop stack unavailable: {exc}") from exc

        cls.Se3RetargeterConfig = Se3RetargeterConfig
        cls.ControllersSource = ControllersSource
        cls.OptionalTensorGroup = OptionalTensorGroup
        cls.ControllerInputIndex = ControllerInputIndex
        cls.ControllerButtonRetargeter = ControllerButtonRetargeter
        cls.ControllerStateRetargeter = ControllerStateRetargeter
        cls.DemoRuntime = DemoRuntime
        cls.TrackingSafeSe3RelRetargeter = TrackingSafeSe3RelRetargeter
        cls.build_piper_x_bimanual_pipeline = staticmethod(build_piper_x_bimanual_pipeline)

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
        primary=0.0,
        secondary=0.0,
        side=None,
    ):
        side = side or self.ControllersSource.LEFT
        group = self.OptionalTensorGroup(retargeter.input_spec()[side])
        group[self.ControllerInputIndex.GRIP_IS_VALID] = valid
        group[self.ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
        group[self.ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
            [0.0, 0.0, 0.0, 1.0] if orientation is None else orientation,
            dtype=np.float32,
        )
        group[self.ControllerInputIndex.SQUEEZE_VALUE] = squeeze
        group[self.ControllerInputIndex.TRIGGER_VALUE] = trigger
        group[self.ControllerInputIndex.THUMBSTICK_CLICK] = sensitivity
        group[self.ControllerInputIndex.PRIMARY_CLICK] = primary
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

    def test_demo_sensitivity_uses_left_y_for_both_arm_state_outputs(self) -> None:
        left = self.ControllersSource.LEFT
        right = self.ControllersSource.RIGHT
        left_state = self.ControllerStateRetargeter(
            left, sensitivity_control="left_secondary_click", name="left_demo_state"
        )
        left_controller = self._controller(left_state, [0.1, 0.2, 0.3], secondary=1.0, side=left)
        state = np.asarray(left_state({left: left_controller})["state"][0])
        self.assertEqual(state[4], 1.0)

        right_state = self.ControllerStateRetargeter(
            right, sensitivity_control="left_secondary_click", name="right_demo_state"
        )
        right_controller = self._controller(right_state, [0.3, 0.2, 0.1], trigger=0.75, side=right)
        left_controller = self._controller(right_state, [0.1, 0.2, 0.3], secondary=1.0, side=left)
        state = np.asarray(
            right_state({left: left_controller, right: right_controller})["state"][0]
        )
        np.testing.assert_allclose(state, [1.0, 1.0, 0.0, 0.75, 1.0])

    def test_demo_display_output_uses_free_left_primary_x_button(self) -> None:
        side = self.ControllersSource.LEFT
        retargeter = self.ControllerButtonRetargeter(
            side, control="primary_click", name="display_test"
        )
        controller = self._controller(
            retargeter,
            [0.1, 0.2, 0.3],
            squeeze=0.25,
            trigger=0.75,
            sensitivity=1.0,
            primary=1.0,
        )
        value = np.asarray(retargeter({side: controller})["button"][0])
        np.testing.assert_array_equal(value, [1.0])

    def test_demo_backdrop_output_uses_free_right_secondary_b_button(self) -> None:
        side = self.ControllersSource.RIGHT
        retargeter = self.ControllerButtonRetargeter(
            side, control="secondary_click", name="backdrop_test"
        )
        controller = self._controller(
            retargeter,
            [0.1, 0.2, 0.3],
            secondary=1.0,
            side=side,
        )
        value = np.asarray(retargeter({side: controller})["button"][0])
        np.testing.assert_array_equal(value, [1.0])

    def test_demo_controls_append_two_values_without_changing_production_shape(self) -> None:
        production = self.build_piper_x_bimanual_pipeline()
        demo = self.build_piper_x_bimanual_pipeline(
            sensitivity_control="left_secondary_click",
            display_control="left_primary_click",
            backdrop_control="right_secondary_click",
        )
        self.assertEqual(production.output_types()["action"].types[0].shape, (22,))
        self.assertEqual(demo.output_types()["action"].types[0].shape, (24,))

    def test_demo_display_edges_hide_panels_without_closing_rgb_source(self) -> None:
        class Container:
            def __init__(self):
                self.show_count = 0
                self.hide_count = 0

            def show(self):
                self.show_count += 1

            def hide(self):
                self.hide_count += 1

        class Feed:
            def __init__(self):
                self.panel = type("Panel", (), {"_container": Container()})()

        class Session:
            def __init__(self):
                self._manager = None
                self.bind_count = 0
                self.refresh_count = 0
                self.close_count = 0

            def bind(self, _env):
                self.bind_count += 1
                self._manager = type("Manager", (), {"_feeds": [Feed(), Feed()]})()

            def refresh(self):
                self.refresh_count += 1

            def close(self):
                self.close_count += 1

        runtime = self.DemoRuntime.__new__(self.DemoRuntime)
        runtime.config = {
            "vr_camera_feeds": {"quest_button": "X"},
        }
        runtime.display_control = "left_primary_click"
        runtime.feed_session_prepared_enabled = True
        runtime._feed_session = Session()
        runtime._env = object()
        runtime._display_visible = False
        runtime._feed_bound = False
        runtime._feed_bound_ever = False
        runtime._display_button_pressed = False
        runtime._display_toggle_count = 0

        runtime.consume_display_button(1.0)
        feeds = runtime._feed_session._manager._feeds
        self.assertTrue(runtime._display_visible)
        self.assertEqual(runtime._feed_session.bind_count, 1)
        self.assertEqual(runtime._feed_session.refresh_count, 1)
        self.assertTrue(all(feed.panel._container.show_count == 1 for feed in feeds))

        runtime.consume_display_button(1.0)
        self.assertEqual(runtime._display_toggle_count, 1)
        runtime.consume_display_button(0.0)
        runtime.consume_display_button(1.0)
        self.assertFalse(runtime._display_visible)
        self.assertEqual(runtime._feed_session.close_count, 0)
        self.assertTrue(all(feed.panel._container.hide_count == 1 for feed in feeds))

        runtime.consume_display_button(0.0)
        runtime.consume_display_button(1.0)
        self.assertTrue(runtime._display_visible)
        self.assertEqual(runtime._feed_session.bind_count, 1)
        self.assertTrue(all(feed.panel._container.show_count == 2 for feed in feeds))

        runtime.close()
        self.assertEqual(runtime._feed_session.close_count, 1)

    def test_demo_backdrop_toggle_is_rising_edge_only(self) -> None:
        runtime = self.DemoRuntime.__new__(self.DemoRuntime)
        runtime.config = {
            "scene": {"backdrop": {"quest_button": "B"}},
        }
        runtime.backdrop_control = "right_secondary_click"
        runtime._backdrop_visible = True
        runtime._backdrop_button_pressed = False
        runtime._backdrop_toggle_count = 0
        runtime._feed_bound = False
        visibility_changes = []

        def set_visibility(visible):
            visibility_changes.append(visible)
            runtime._backdrop_visible = visible

        runtime._set_backdrop_visibility = set_visibility
        runtime.consume_backdrop_button(1.0)
        runtime.consume_backdrop_button(1.0)
        runtime.after_reset()
        runtime.consume_backdrop_button(1.0)
        self.assertEqual(visibility_changes, [False, False])
        self.assertEqual(runtime._backdrop_toggle_count, 1)

        runtime.consume_backdrop_button(0.0)
        runtime.consume_backdrop_button(1.0)
        self.assertEqual(visibility_changes, [False, False, True])
        self.assertEqual(runtime._backdrop_toggle_count, 2)


if __name__ == "__main__":
    unittest.main()
