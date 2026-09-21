"""Pinned Candidate B tests for the narrow S2 relative-reference adapter."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
                PiperXIsaacTeleopDevice,
                TrackingSafeSe3RelRetargeter,
                _gf_row_matrix_to_numpy_transform,
                _NavigationAwareXrAnchorManager,
                build_piper_x_bimanual_pipeline,
            )
            from tools.isaac_vr_runtime import (
                VRRuntime,
                _CameraFeedFrameDiagnostics,
                _CpuRgbaPanel,
                _CpuStagedFeedPresenter,
                _FreshVisibleFeedUpdates,
            )
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest(f"Candidate B teleop stack unavailable: {exc}") from exc

        cls.Se3RetargeterConfig = Se3RetargeterConfig
        cls.ControllersSource = ControllersSource
        cls.OptionalTensorGroup = OptionalTensorGroup
        cls.ControllerInputIndex = ControllerInputIndex
        cls.ControllerButtonRetargeter = ControllerButtonRetargeter
        cls.ControllerStateRetargeter = ControllerStateRetargeter
        cls.PiperXIsaacTeleopDevice = PiperXIsaacTeleopDevice
        cls.VRRuntime = VRRuntime
        cls.CameraFeedFrameDiagnostics = _CameraFeedFrameDiagnostics
        cls.CpuStagedFeedPresenter = _CpuStagedFeedPresenter
        cls.CpuRgbaPanel = _CpuRgbaPanel
        cls.FreshVisibleFeedUpdates = _FreshVisibleFeedUpdates
        cls.TrackingSafeSe3RelRetargeter = TrackingSafeSe3RelRetargeter
        cls.NavigationAwareXrAnchorManager = _NavigationAwareXrAnchorManager
        cls.gf_row_matrix_to_numpy_transform = staticmethod(_gf_row_matrix_to_numpy_transform)
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
        thumbstick_x=0.0,
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
        group[self.ControllerInputIndex.THUMBSTICK_X] = thumbstick_x
        group[self.ControllerInputIndex.PRIMARY_CLICK] = primary
        group[self.ControllerInputIndex.SECONDARY_CLICK] = secondary
        return group

    def _delta(self, retargeter, group):
        result = retargeter({next(iter(retargeter.input_spec())): group})["ee_delta"][0]
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

    def test_demo_slider_uses_each_controllers_own_thumbstick_x(self) -> None:
        for side, value in (
            (self.ControllersSource.LEFT, -0.75),
            (self.ControllersSource.RIGHT, 0.625),
        ):
            retargeter = self.ControllerStateRetargeter(
                side, sensitivity_control="thumbstick_x", name=f"{side}_slider_state"
            )
            controller = self._controller(
                retargeter,
                [0.1, 0.2, 0.3],
                thumbstick_x=value,
                side=side,
            )
            state = np.asarray(retargeter({side: controller})["state"][0])
            self.assertAlmostEqual(float(state[4]), value)

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

    def test_demo_recenter_output_uses_free_right_thumbstick_click(self) -> None:
        side = self.ControllersSource.RIGHT
        retargeter = self.ControllerButtonRetargeter(
            side, control="thumbstick_click", name="recenter_test"
        )
        controller = self._controller(
            retargeter,
            [0.1, 0.2, 0.3],
            sensitivity=1.0,
            side=side,
        )
        value = np.asarray(retargeter({side: controller})["button"][0])
        np.testing.assert_array_equal(value, [1.0])

    def test_demo_controls_append_three_values_without_changing_production_shape(self) -> None:
        production = self.build_piper_x_bimanual_pipeline()
        demo = self.build_piper_x_bimanual_pipeline(
            sensitivity_control="thumbstick_x",
            display_control="left_primary_click",
            backdrop_control="right_secondary_click",
            recenter_control="right_thumbstick_click",
        )
        self.assertEqual(production.output_types()["action"].types[0].shape, (22,))
        self.assertEqual(demo.output_types()["action"].types[0].shape, (25,))

    def test_demo_display_edges_hide_panels_without_closing_rgb_source(self) -> None:
        import torch

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
                self.panel = SimpleNamespace(
                    _container=Container(),
                    _component=SimpleNamespace(
                        width=0.36,
                        height=0.31,
                        unit_to_pixel_scale=640 / 0.36,
                        resolution_scale=1.0,
                    ),
                )
                self.cfg = type("Cfg", (), {"camera_name": "wrist"})()
                self.image_source = None
                self.image = torch.full((2, 2, 4), 255, dtype=torch.uint8)
                self.upload_image = self.image.clone()

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

        runtime = self.VRRuntime.__new__(self.VRRuntime)
        runtime.preview_scene = False
        runtime.preview_isolation = None
        runtime.config = {
            "vr_camera_feeds": {
                "quest_button": "X",
                "layout": {"placement": "head_locked"},
            },
        }
        runtime.display_control = "left_primary_click"
        runtime.feed_upload_path = "cpu_staged"
        runtime.feed_session_prepared_enabled = True
        runtime._feed_session = Session()
        runtime._env = object()
        runtime._display_visible = False
        runtime._feed_bound = False
        runtime._feed_bound_ever = False
        runtime._display_button_pressed = False
        runtime._display_toggle_count = 0

        runtime._prebind_camera_panels()
        feeds = runtime._feed_session._manager._feeds
        self.assertEqual(runtime._feed_session.bind_count, 1)
        self.assertEqual(runtime._feed_session.refresh_count, 1)
        self.assertTrue(all(feed.panel._container.hide_count == 1 for feed in feeds))

        runtime.consume_display_button(1.0)
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
        self.assertTrue(all(feed.panel._container.hide_count == 2 for feed in feeds))

        runtime.consume_display_button(0.0)
        runtime.consume_display_button(1.0)
        self.assertTrue(runtime._display_visible)
        self.assertEqual(runtime._feed_session.bind_count, 1)
        self.assertTrue(all(feed.panel._container.show_count == 2 for feed in feeds))

        runtime.close()
        self.assertEqual(runtime._feed_session.close_count, 1)

    def test_demo_recenter_is_edge_triggered_and_uses_upstream_xr_teleport(self) -> None:
        runtime = self.VRRuntime.__new__(self.VRRuntime)
        runtime.config = {
            "xr_presentation": {"recenter": {"quest_button": "R3"}},
        }
        runtime.recenter_control = "right_thumbstick_click"
        runtime.recenter_view_prim_path = "/World/RobosynDemo/SceneCamera"
        runtime._recenter_button_pressed = False
        runtime._recenter_request_count = 0
        runtime._recenter_scheduled_count = 0
        calls = []

        def schedule():
            calls.append(True)
            return True

        self.assertTrue(runtime.consume_recenter_button(1.0, schedule_recenter=schedule))
        self.assertFalse(runtime.consume_recenter_button(1.0, schedule_recenter=schedule))
        self.assertFalse(runtime.consume_recenter_button(0.0, schedule_recenter=schedule))
        self.assertTrue(runtime.consume_recenter_button(1.0, schedule_recenter=schedule))
        self.assertEqual(len(calls), 2)
        self.assertEqual(runtime.recenter_request_count, 2)
        self.assertEqual(runtime.recenter_scheduled_count, 2)

        class XrCore:
            def __init__(self):
                self.teleports = []

            @staticmethod
            def is_xr_display_enabled():
                return True

            @staticmethod
            def get_world_transform_matrix(path):
                return np.eye(4).tolist()

            def schedule_teleport_to_view(self, anchor, pose):
                self.teleports.append((anchor, pose))

        class Lifecycle:
            def __init__(self):
                self.resets = []
                self.haptic_resets = 0

            def request_reset(self, pause=False):
                self.resets.append(pause)

            def reset_haptics(self):
                self.haptic_resets += 1

        xr_core = XrCore()
        lifecycle = Lifecycle()
        device = self.PiperXIsaacTeleopDevice.__new__(self.PiperXIsaacTeleopDevice)
        from tools.isaac_vr_decision import XrInputReceipt
        device.xr_receipt = XrInputReceipt()
        device._anchor_manager = type(
            "AnchorManager",
            (),
            {
                "xr_core": xr_core,
                "anchor_headset_path": "/World/XRAnchor",
                "cleanup": lambda self: None,
            },
        )()
        device._include_xr_navigation_in_controller_transform = True
        device._session_lifecycle = lifecycle
        self.assertTrue(device.schedule_recenter_to_view(runtime.recenter_view_prim_path))
        self.assertEqual(
            xr_core.teleports,
            [
                (
                    "/World/XRAnchor",
                    np.eye(4).tolist(),
                )
            ],
        )
        self.assertEqual(lifecycle.resets, [])
        self.assertEqual(lifecycle.haptic_resets, 1)

    def test_demo_recenter_controller_transform_tracks_xr_space_origin(self) -> None:
        class Matrix:
            def __init__(self, rows):
                self.rows = rows

            def __getitem__(self, index):
                return self.rows[index]

        first = Matrix(
            [
                [0.0, 1.0, 0.0, 0.0],
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.1, 0.2, 0.3, 1.0],
            ]
        )
        second = Matrix(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.8, -0.4, 1.2, 1.0],
            ]
        )

        class XrCore:
            matrix = first

            @staticmethod
            def is_xr_display_enabled():
                return True

            def get_physical_to_virtual_world_transform(self):
                return self.matrix

        manager = self.NavigationAwareXrAnchorManager.__new__(self.NavigationAwareXrAnchorManager)
        manager._xr_core = XrCore()

        np.testing.assert_allclose(
            manager.get_world_matrix(),
            np.asarray(
                [
                    [0.0, -1.0, 0.0, 0.1],
                    [1.0, 0.0, 0.0, 0.2],
                    [0.0, 0.0, 1.0, 0.3],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                dtype=np.float32,
            ),
        )
        manager._xr_core.matrix = second
        np.testing.assert_allclose(
            manager.get_world_matrix(),
            np.asarray(
                [
                    [1.0, 0.0, 0.0, 0.8],
                    [0.0, 1.0, 0.0, -0.4],
                    [0.0, 0.0, 1.0, 1.2],
                    [0.0, 0.0, 0.0, 1.0],
                ],
                dtype=np.float32,
            ),
        )

    def _navigation_device(self):
        class Core:
            matrix = np.eye(4).tolist()
            requested = np.eye(4)
            requested[3, :3] = [0.6, 0.1, 1.4]
            teleports = []

            def is_xr_display_enabled(self):
                return True

            def get_physical_to_virtual_world_transform(self):
                return self.matrix

            def get_world_transform_matrix(self, path):
                return self.requested.tolist()

            def schedule_teleport_to_view(self, anchor, pose):
                self.teleports.append((anchor, pose))

        core = Core()
        manager = self.NavigationAwareXrAnchorManager.__new__(self.NavigationAwareXrAnchorManager)
        manager._xr_core = core
        manager._xr_anchor_headset_path = "/World/XRAnchor"
        lifecycle = SimpleNamespace(
            resets=[],
            request_reset=lambda pause=False: lifecycle.resets.append(pause),
            reset_haptics=lambda: None,
        )
        device = self.PiperXIsaacTeleopDevice.__new__(self.PiperXIsaacTeleopDevice)
        from tools.isaac_vr_decision import XrInputReceipt
        device.xr_receipt = XrInputReceipt()
        device._anchor_manager = manager
        device._session_lifecycle = lifecycle
        device._include_xr_navigation_in_controller_transform = True
        device._recenter_rebase_pending = False
        device._last_navigation_transform = None
        device._navigation_epoch = 0
        return device, core, lifecycle

    def test_recenter_accepts_next_xr_frame_and_rebases_later_transform_change(self) -> None:
        device, core, lifecycle = self._navigation_device()
        self.assertTrue(device.schedule_recenter_to_view("/World/Camera"))
        base = self.PiperXIsaacTeleopDevice.__bases__[0]
        with patch.object(base, "advance", return_value="fresh_frame"):
            self.assertEqual(device._advance_navigation(), "fresh_frame")
            self.assertTrue(device.navigation_reset_applied)
            self.assertEqual(lifecycle.resets, [False])
            self.assertEqual(device._advance_navigation(), "fresh_frame")
            self.assertFalse(device.navigation_reset_applied)
            self.assertEqual(lifecycle.resets, [False])
            # XR may apply the space-origin change after the first control
            # boundary. The observed transform change gets its own safe rebase.
            core.matrix = core.requested.tolist()
            self.assertEqual(device._advance_navigation(), "fresh_frame")
            self.assertTrue(device.navigation_reset_applied)
            self.assertEqual(lifecycle.resets, [False, False])
            # The already reached viewpoint is a valid repeat/no-op target.
            device.schedule_recenter_to_view("/World/Camera")
            self.assertEqual(device._advance_navigation(), "fresh_frame")
            self.assertEqual(lifecycle.resets, [False, False, False])

    def test_active_xr_missing_or_invalid_transform_holds_and_rebases_on_recovery(self) -> None:
        device, core, lifecycle = self._navigation_device()
        base = self.PiperXIsaacTeleopDevice.__bases__[0]
        with patch.object(base, "advance", return_value="fresh_frame") as advance:
            core.matrix = None
            self.assertIsNone(device._advance_navigation())
            with self.assertRaises(RuntimeError):
                device._anchor_manager.get_world_matrix()
            core.matrix = np.full((4, 4), np.nan).tolist()
            self.assertIsNone(device._advance_navigation())
            advance.assert_not_called()
            core.matrix = np.eye(4).tolist()
            self.assertEqual(device._advance_navigation(), "fresh_frame")
            self.assertEqual(lifecycle.resets, [False])

    def test_rightward_relative_motion_preserves_direction_after_navigation_yaw(self) -> None:
        from scipy.spatial.transform import Rotation

        basis = Rotation.from_euler("x", 90, degrees=True).as_matrix()
        for side in (self.ControllersSource.LEFT, self.ControllersSource.RIGHT):
            for yaw in (0, 90, 180, -90):
                rotation = Rotation.from_euler("z", yaw, degrees=True).as_matrix() @ basis
                matrix = np.eye(4)
                matrix[:3, :3] = rotation
                matrix[:3, 3] = [0.6, 0.1, 1.4]
                transformed = self.gf_row_matrix_to_numpy_transform(matrix.T.tolist())
                retargeter = self.TrackingSafeSe3RelRetargeter(
                    self.Se3RetargeterConfig(input_device=side, delta_pos_scale_factor=1.0),
                    "navigation_axes",
                )
                p0 = transformed[:3, :3] @ [0.2, 1.2, -0.4] + transformed[:3, 3]
                p1 = p0 + transformed[:3, :3] @ [0.01, 0, 0]
                np.testing.assert_array_equal(
                    self._delta(retargeter, self._controller(retargeter, p0, side=side)),
                    np.zeros(6),
                )
                delta = self._delta(retargeter, self._controller(retargeter, p1, side=side))
                np.testing.assert_allclose(delta[:3], 0.005 * rotation[:, 0], atol=1e-6)

    def test_demo_camera_feed_cpu_staging_preserves_rgba_and_reuses_buffer(self) -> None:
        import torch

        source = torch.zeros((8, 12, 4), dtype=torch.uint8)
        source[..., :3] = 73
        source[..., 3] = 0
        upload = torch.empty_like(source)

        self.CpuStagedFeedPresenter.stage_upload_image(source, upload)

        self.assertTrue(torch.equal(upload, source))
        reused = self.CpuStagedFeedPresenter.prepare_upload_image(
            "left_wrist",
            type(
                "CudaImage",
                (),
                {
                    "device": type("Device", (), {"type": "cuda"})(),
                    "shape": source.shape,
                    "dtype": source.dtype,
                },
            )(),
            previous_upload=upload,
        )
        self.assertIs(reused, upload)

    def test_demo_camera_feed_uses_camera_buffer_without_feedback_annotator(self) -> None:
        upstream = SimpleNamespace(
            create_image_source=lambda *_: self.fail("feedback annotator must not be created")
        )
        presenter = self.CpuStagedFeedPresenter(upstream)
        self.assertIsNone(presenter.create_image_source("left_wrist", object(), object()))

    def test_camera_feed_diagnostics_preserve_source_and_upload_boundary(self) -> None:
        import torch

        source = torch.zeros((3, 4, 4), dtype=torch.uint8)
        source[..., 0] = 17
        source[..., 3] = 255
        feed = SimpleNamespace(
            cfg=SimpleNamespace(camera_name="left_wrist"),
            image=source,
            upload_image=source.clone(),
        )
        with tempfile.TemporaryDirectory() as directory:
            diagnostics = self.CameraFeedFrameDiagnostics(Path(directory), max_per_feed=1)
            diagnostics.capture(feed, 1, "display-visible-1")
            diagnostics.capture(feed, 2, "display-visible-2")
            manifest = json.loads(Path(directory, "manifest.json").read_text())
            self.assertEqual(len(manifest), 1)
            self.assertTrue(manifest[0]["source_upload_identical"])
            self.assertEqual(manifest[0]["shape"], [3, 4, 4])
            self.assertEqual(
                Path(directory, manifest[0]["source"]).read_bytes(),
                b"P6\n4 3\n255\n" + source[..., :3].numpy().tobytes(),
            )

    def test_demo_panel_uses_pixels_for_layout_without_changing_physical_size(self) -> None:
        for meters_per_unit in (1.0, 0.01):
            component = SimpleNamespace(
                width=0.36 / meters_per_unit,
                height=0.31 / meters_per_unit,
                resolution_scale=640 / 0.36,
                unit_to_pixel_scale=meters_per_unit,
            )
            panel = SimpleNamespace(_component=component)
            descriptor = SimpleNamespace(label="LEFT WRIST")
            calls = []

            def create_panel(*args):
                calls.append(args)
                return panel

            presenter = self.CpuStagedFeedPresenter(SimpleNamespace(create_panel=create_panel))
            self.assertIs(presenter.create_panel(descriptor, 640, 480)._upstream, panel)
            self.assertEqual(calls, [(descriptor, 640, 480)])
            self.assertEqual(component.width, 0.36 / meters_per_unit)
            self.assertEqual(component.height, 0.31 / meters_per_unit)
            self.assertEqual(component.resolution_scale, 1.0)
            self.assertAlmostEqual(component.width * component.unit_to_pixel_scale, 640)
            self.assertGreater(component.height * component.unit_to_pixel_scale, 480 + 22)

    def test_raw_cpu_upload_preserves_bytes_and_retains_buffer_until_close(self) -> None:
        import ctypes
        import sys
        import torch

        uploads, invalidations, closes = [], [], []
        pointer = ctypes.PYFUNCTYPE(ctypes.c_void_p, ctypes.py_object, ctypes.c_char_p)(
            ctypes.cast(ctypes.pythonapi.PyCapsule_GetPointer, ctypes.c_void_p).value
        )

        def upload(capsule, size, fmt):
            uploads.append(
                (ctypes.string_at(pointer(capsule, None), size[0] * size[1] * 4), size, fmt)
            )

        widget = SimpleNamespace(invalidate=lambda: invalidations.append(True))
        upstream = SimpleNamespace(
            _provider=SimpleNamespace(set_raw_bytes_data=upload),
            _component=SimpleNamespace(scene_widget=widget),
            close=lambda: closes.append(True),
        )
        panel = self.CpuRgbaPanel(upstream)
        image = torch.arange(48, dtype=torch.uint8).reshape(3, 4, 4)
        gf = SimpleNamespace(TextureFormat=SimpleNamespace(RGBA8_UNORM="RGBA8"))
        sc = SimpleNamespace(
            Widget=SimpleNamespace(UpdatePolicy=SimpleNamespace(ON_DEMAND="demand"))
        )
        with patch.dict(sys.modules, {"omni.gpu_foundation_factory": gf, "omni.ui.scene": sc}):
            panel.upload(image)
            self.assertEqual(uploads, [(image.numpy().tobytes(), [4, 3], "RGBA8")])
            self.assertIs(panel._retained_image, image)
            self.assertEqual(widget.update_policy, "demand")
            self.assertEqual(invalidations, [True])
            with self.assertRaises(TypeError):
                panel.upload(image.float())
            with self.assertRaises(ValueError):
                panel.upload(image[:, ::2])
            panel.close()
            panel.close()
            panel.upload(image)
        self.assertEqual(len(uploads), 1)
        self.assertIsNone(panel._retained_image)
        self.assertEqual(closes, [True])

    def test_preview_skips_hidden_and_duplicate_frames_before_acquisition(self) -> None:
        import torch
        from isaaclab_teleop.camera_feed import _XrCameraFeedManager

        acquired = []
        feeds = [
            SimpleNamespace(
                cfg=SimpleNamespace(camera_name=side, max_update_hz=30.0),
                camera=SimpleNamespace(frame=torch.tensor([7])),
                next_update_time=0.0,
            )
            for side in ("left", "right")
        ]
        manager = SimpleNamespace(
            _feeds=feeds, _publish_feed=lambda f: acquired.append(f.cfg.camera_name)
        )
        visible = [False]
        updates = self.FreshVisibleFeedUpdates(manager, lambda: visible[0])
        manager.update = updates.update
        with patch("tools.isaac_vr_runtime.time.monotonic", return_value=1.0):
            _XrCameraFeedManager._on_frame(manager, None)
            self.assertEqual(acquired, [])
            visible[0] = True
            _XrCameraFeedManager._on_frame(manager, None)
            self.assertEqual(acquired, ["left", "right"])
        with patch("tools.isaac_vr_runtime.time.monotonic", return_value=1.1):
            manager.update()
            self.assertEqual(acquired, ["left", "right"])
            feeds[1].camera.frame += 1
            manager.update()
            self.assertEqual(acquired, ["left", "right", "right"])
            visible[0] = False
            feeds[0].camera.frame += 1
            manager.update()
            self.assertEqual(len(acquired), 3)
            visible[0] = True
            manager.update()
            self.assertEqual(acquired[-1], "left")
        self.assertEqual(updates.counters["hidden_callbacks"], 2)
        self.assertGreater(updates.counters["duplicate_frames"], 0)

    def test_preview_throttle_keeps_latest_frame_and_reset_invalidates_identity(self) -> None:
        import torch

        acquired = []
        feed = SimpleNamespace(
            cfg=SimpleNamespace(camera_name="left", max_update_hz=30.0),
            camera=SimpleNamespace(frame=torch.tensor([7])),
            next_update_time=0.0,
        )
        manager = SimpleNamespace(
            _feeds=[feed], _publish_feed=lambda f: acquired.append(int(f.camera.frame[0]))
        )
        updates = self.FreshVisibleFeedUpdates(manager, lambda: True)
        for now, frame in ((1.0, 7), (1.01, 8), (1.02, 9), (1.04, 10)):
            feed.camera.frame[0] = frame
            with patch("tools.isaac_vr_runtime.time.monotonic", return_value=now):
                updates.update()
        self.assertEqual(acquired, [7, 10])
        # A reset can reuse the same numeric frame. A replacement camera can too.
        updates.invalidate()
        with patch("tools.isaac_vr_runtime.time.monotonic", return_value=1.1):
            updates.update()
        feed.camera = SimpleNamespace(frame=torch.tensor([10]))
        with patch("tools.isaac_vr_runtime.time.monotonic", return_value=1.2):
            updates.update()
        self.assertEqual(acquired, [7, 10, 10, 10])
        self.assertEqual(updates.counters["throttled_frames"], 2)

    def test_demo_backdrop_toggle_is_rising_edge_only(self) -> None:
        runtime = self.VRRuntime.__new__(self.VRRuntime)
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


class XrDecisionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        IsaacS2UpstreamTests.setUpClass()

    def fixture(self):
        from isaacteleop import schema
        from isaacteleop.teleop_session_manager import (
            TeleopSession, TeleopSessionConfig, RetargetingExecutionConfig,
        )
        from isaacteleop.retargeting_engine.interface import TensorGroup
        from isaacteleop.retargeting_engine.tensor_types import TransformMatrix
        from tools.isaac_s2_upstream import build_piper_x_bimanual_pipeline
        from tools.isaac_vr_decision import XrInputReceipt
        receipt = XrInputReceipt()
        pipeline = build_piper_x_bimanual_pipeline(receipt=receipt)
        session = TeleopSession(TeleopSessionConfig(
            app_name="synthetic_source", pipeline=pipeline,
            retargeting_execution=RetargetingExecutionConfig(mode="sync")))
        receipt.session_provider = lambda: session
        counters = dict(update=0, left=0, right=0)
        snapshots = []
        for side in range(2):
            pose = schema.ControllerPose(
                schema.Pose(schema.Point(side + .25, 0., 0.), schema.Quaternion(w=1.)), True)
            snap = schema.ControllerSnapshot(pose, pose, schema.ControllerInputState(
                True, True, True, True, -.25, .75, .5, .25 + side * .5))
            snapshots.append(snap)
        def update():
            counters['update'] += 1
        def poll(side):
            counters[side] += 1
            assert counters[side] == counters['update']
            snap = snapshots[side == 'right']
            return (schema.ControllerSnapshotTrackedT() if snap is None else
                    schema.ControllerSnapshotTrackedT(data=snap))
        self.assertEqual(len(session._sources), 1)
        session._sources[0]._controller_tracker = SimpleNamespace(
            get_left_controller=lambda _: poll('left'), get_right_controller=lambda _: poll('right'))
        session.deviceio_session = SimpleNamespace(update=update)
        transform = TensorGroup(TransformMatrix())
        transform[0] = np.eye(4, dtype=np.float32)
        inputs = {"world_T_anchor": {"value": transform}}
        return receipt, session, snapshots, counters, inputs

    def test_actual_upstream_sync_update_source_conversion_owned_inputs(self):
        from dataclasses import replace
        receipt, session, snapshots, counts, inputs = self.fixture()
        result = session.step(external_inputs=inputs)
        xr = receipt.resolve(session.last_step_info, 0)
        self.assertEqual(counts, dict(update=1, left=1, right=1))
        self.assertEqual((xr.submitted_frame_id, xr.returned_frame_id), (0, 0))
        for side, hand in enumerate(xr.hands):
            values = dict(hand)
            self.assertEqual(values['GRIP_POSITION'][0], side + .25)
            for button in ('PRIMARY_CLICK', 'SECONDARY_CLICK', 'MENU_CLICK', 'THUMBSTICK_CLICK'):
                self.assertEqual(values[button], 1.)
            self.assertEqual(values['THUMBSTICK_X'], -.25)
            self.assertEqual(values['THUMBSTICK_Y'], .75)
            self.assertEqual(values['SQUEEZE_VALUE'], .5)
            self.assertEqual(values['TRIGGER_VALUE'], .25 + side * .5)
        before = xr.hands
        snapshots[0] = snapshots[1]
        session.step(external_inputs=inputs)
        self.assertEqual(xr.hands, before)
        self.assertEqual(counts, dict(update=2, left=2, right=2))
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            receipt.resolve(replace(session.last_step_info, returned_frame_id=0), 1)
        self.assertEqual(np.from_dlpack(result['action'][0]).shape, (22,))
        xr2 = receipt.resolve(session.last_step_info, 1)
        receipt.validate(xr2)
        receipt.last_consumed = xr2.deviceio_update_epoch
        with self.assertRaisesRegex(RuntimeError, 'reused'):
            receipt.validate(xr2)

    def test_missing_invalid_hand_and_reference_change(self):
        from isaacteleop.retargeting_engine.interface.execution_events import (
            ExecutionEvents, ExecutionState,
        )
        receipt, session, snapshots, counts, inputs = self.fixture()
        snapshots[0] = None
        from isaacteleop import schema
        snapshots[1] = schema.ControllerSnapshot()
        session.step(external_inputs=inputs)
        xr = receipt.resolve(session.last_step_info, 0)
        self.assertIsNone(xr.hands[0])
        self.assertEqual(dict(xr.hands[1])['GRIP_IS_VALID'], 0.)
        previous_epoch = xr.control_reference_epoch
        inputs['world_T_anchor']['value'][0] = np.diag([1., -1., -1., 1.]).astype(np.float32)
        session.step(external_inputs=inputs, execution_events=ExecutionEvents(
            reset=True, execution_state=ExecutionState.RUNNING))
        newer = receipt.resolve(session.last_step_info, 1)
        self.assertGreater(newer.control_reference_epoch, previous_epoch)
        self.assertTrue(newer.rebased)
        with self.assertRaises(RuntimeError):
            receipt.validate(xr)
        old_session_epoch = receipt.session_epoch
        session.deviceio_session = SimpleNamespace(update=lambda: counts.update(update=counts['update'] + 1))
        session.step(external_inputs=inputs)
        self.assertGreater(receipt.session_epoch, old_session_epoch)

    def test_actual_differential_ik_preclip_native_parity(self):
        import ast
        import subprocess
        from typing import Any
        import torch
        from isaaclab.controllers import DifferentialIKController, DifferentialIKControllerCfg
        from tools.isaac_s1_runtime import NativeBimanualTargets
        from tools.isaac_s2_processor import BimanualS2TeleopProcessor, ControllerDeltaSample
        from tools.isaac_vr_decision import SolvedControlDecision, check_observation
        root = Path(__file__).resolve().parents[1]
        cfg = DifferentialIKControllerCfg(command_type='pose', use_relative_mode=True, ik_method='dls')
        wrappers = []
        for baseline in (True, False):
            source = subprocess.check_output([
                'git', 'show', '4423cacfd1ed226bc0169cc55890589e2a5b2a4c:tools/isaac_s2_runtime.py'
            ], cwd=root, text=True) if baseline else (root / 'tools/isaac_s2_runtime.py').read_text()
            node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)
                        and n.name == '_BimanualDifferentialIk')
            ns = dict(np=np, Any=Any, BimanualS2TeleopProcessor=BimanualS2TeleopProcessor,
                      NativeBimanualTargets=NativeBimanualTargets,
                      SolvedControlDecision=SolvedControlDecision, check_observation=check_observation)
            exec(compile(ast.Module([node], []), 'pinned_ik_parity', 'exec'), ns)
            cls = ns['_BimanualDifferentialIk']
            ik = cls.__new__(cls)
            ik.torch = torch
            ik.controllers = tuple(DifferentialIKController(cfg, num_envs=1, device='cpu') for _ in range(2))
            robots = [SimpleNamespace(data=SimpleNamespace(
                joint_limits=SimpleNamespace(torch=torch.tensor([[[-.1, .1]] * 6])),
                joint_pos=SimpleNamespace(torch=torch.full((1, 6), .031234567)),
                body_link_pose_w=SimpleNamespace(torch=torch.tensor([[[0., 0., 0., 0., 0., 0., 1.]]])),
                body_link_jacobian_w=SimpleNamespace(torch=torch.eye(6).reshape(1, 1, 6, 6))),
                is_fixed_base=True, num_base_dofs=0) for _ in range(2)]
            applied = []
            ik.env = SimpleNamespace(robots=robots, wrist_ids=[0, 0], joint_ids=[list(range(6))] * 2,
                                     sim=SimpleNamespace(device='cpu'), _apply=applied.append)
            wrappers.append((ik, applied))
        proc = BimanualS2TeleopProcessor()
        for delta in (0., .001, .01, 1., 0.):
            sample = ControllerDeltaSample(np.full(3, delta), np.full(3, delta), True, True, 0., .25, 0.)
            command = proc.advance(sample, sample)
            old, old_applied = wrappers[0]
            new, new_applied = wrappers[1]
            old_saturated = old.apply(command)
            solution = new.solve(command)
            self.assertEqual(new.apply(solution), old_saturated)
            for side in ('left_rad_m', 'right_rad_m'):
                self.assertEqual(getattr(old_applied[-1], side).tobytes(),
                                 getattr(new_applied[-1], side).tobytes())
