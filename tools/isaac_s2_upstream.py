"""Pinned Candidate B Isaac Teleop composition for Gate S2.

This module is imported only after AppLauncher starts inside the isolated Isaac
environment. It deliberately builds one ControllersSource carrying both hands.
"""

from __future__ import annotations

import json
import time
from typing import Any

import numpy as np

from isaacteleop.retargeters import (  # type: ignore[import-not-found]
    Se3RelRetargeter,
    Se3RetargeterConfig,
    TensorReorderer,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import (  # type: ignore[import-not-found]
    ControllersSource,
)
from isaacteleop.retargeting_engine.interface import (  # type: ignore[import-not-found]
    BaseRetargeter,
    OutputCombiner,
    ValueInput,
)
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (  # type: ignore[import-not-found]
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import (  # type: ignore[import-not-found]
    OptionalType,
    TensorGroupType,
)
from isaacteleop.retargeting_engine.tensor_types import (  # type: ignore[import-not-found]
    ControllerInput,
    ControllerInputIndex,
    DLDataType,
    NDArrayType,
    TransformMatrix,
)
from isaaclab_teleop.command_handler import CommandHandler  # type: ignore[import-not-found]
from isaaclab_teleop.isaac_teleop_cfg import IsaacTeleopCfg  # type: ignore[import-not-found]
from isaaclab_teleop.isaac_teleop_device import (  # type: ignore[import-not-found]
    IsaacTeleopDevice,
    _enable_teleop_bridge,
)
from isaaclab_teleop.session_lifecycle import (  # type: ignore[import-not-found]
    TeleopSessionLifecycle,
)
from isaaclab_teleop.xr_anchor_manager import XrAnchorManager  # type: ignore[import-not-found]


PIPELINE_ACTION_DIM = 22
DEMO_PIPELINE_ACTION_DIM = 25
DEMO_DISPLAY_BUTTON_INDEX = 22
DEMO_BACKDROP_BUTTON_INDEX = 23
DEMO_RECENTER_BUTTON_INDEX = 24


def _gf_row_matrix_to_numpy_transform(matrix: Any) -> np.ndarray:
    """Convert a USD/Gf row-vector matrix to the pipeline's column-vector convention."""

    values = np.asarray(
        [[float(matrix[row][column]) for column in range(4)] for row in range(4)],
        dtype=np.float32,
    ).T
    if not np.isfinite(values).all():
        raise RuntimeError("XR physical-to-virtual transform contains non-finite values")
    if not np.allclose(values[3], [0.0, 0.0, 0.0, 1.0], atol=1.0e-5):
        raise RuntimeError("XR physical-to-virtual transform is not affine")
    return values


class _XrWorldTransformUnavailable(RuntimeError):
    """An active XR session cannot currently map physical poses into the world."""


class _NavigationAwareXrAnchorManager(XrAnchorManager):
    """Include XRCore space-origin navigation in the controller world transform.

    ``XrAnchorManager.get_world_matrix`` intentionally represents the authored
    stage anchor. Kit teleport/recenter additionally changes XR's space origin,
    which is not part of that matrix. XRCore exposes the full physical-to-
    virtual transform specifically for consumers of raw physical poses.
    """

    def get_world_matrix(self) -> np.ndarray:
        xr_core = self.xr_core
        if xr_core is not None and xr_core.is_xr_display_enabled():
            physical_to_virtual = xr_core.get_physical_to_virtual_world_transform()
            if physical_to_virtual is None:
                raise _XrWorldTransformUnavailable(
                    "active XR physical-to-virtual transform is unavailable"
                )
            try:
                return _gf_row_matrix_to_numpy_transform(physical_to_virtual)
            except RuntimeError as exc:
                raise _XrWorldTransformUnavailable(str(exc)) from exc
        return super().get_world_matrix()


def _controller_grip_pose_is_usable(controller: Any) -> bool:
    """Reject absent, explicitly invalid, non-finite, and zero-quaternion poses."""

    if controller.is_none or not bool(controller[ControllerInputIndex.GRIP_IS_VALID]):
        return False
    position = np.from_dlpack(controller[ControllerInputIndex.GRIP_POSITION])
    orientation = np.from_dlpack(controller[ControllerInputIndex.GRIP_ORIENTATION])
    return bool(
        np.isfinite(position).all()
        and np.isfinite(orientation).all()
        and np.linalg.norm(orientation) > 1.0e-8
    )


class TrackingSafeSe3RelRetargeter(Se3RelRetargeter):
    """Close Candidate B's absent-controller relative-reference gap.

    Pinned ``Se3RelRetargeter`` already invalidates its baseline when a present
    controller reports ``GRIP_IS_VALID=false``.  Its ``is_none`` branch emits
    zero but retains the old pose and smoothing accumulator.  A controller
    recovering at another physical pose therefore creates one large stale
    delta and filtered residuals.  This narrow adapter applies the same reset
    semantics to every unusable pose before delegating valid samples upstream.
    """

    def _invalidate_relative_reference(self) -> None:
        self._smoothed_delta_pos = np.zeros(3)
        self._smoothed_delta_rot = np.zeros(3)
        self._previous_wrist = np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self._previous_thumb_tip = None
        self._previous_index_tip = None
        self._first_frame = True

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        controller = inputs[self._config.input_device]
        if not _controller_grip_pose_is_usable(controller):
            self._invalidate_relative_reference()
            outputs["ee_delta"][0] = np.zeros(6, dtype=np.float32)
            return
        super()._compute_fn(inputs, outputs, context)


class ControllerStateRetargeter(BaseRetargeter):
    """Expose validity and the three S2 controls for one controller side."""

    def __init__(self, side: str, sensitivity_control: str, name: str) -> None:
        if side not in (ControllersSource.LEFT, ControllersSource.RIGHT):
            raise ValueError(f"unsupported controller source: {side}")
        sensitivity_sources = {
            "thumbstick_click": (side, ControllerInputIndex.THUMBSTICK_CLICK),
            "left_secondary_click": (
                ControllersSource.LEFT,
                ControllerInputIndex.SECONDARY_CLICK,
            ),
        }
        if sensitivity_control not in sensitivity_sources:
            raise ValueError(f"unsupported sensitivity control: {sensitivity_control}")
        self._side = side
        self._sensitivity_side, self._sensitivity_index = sensitivity_sources[sensitivity_control]
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        sides = (
            (self._side,)
            if self._side == self._sensitivity_side
            else (self._side, self._sensitivity_side)
        )
        return {side: OptionalType(ControllerInput()) for side in sides}

    def output_spec(self) -> RetargeterIOType:
        return {
            "state": TensorGroupType(
                "state",
                [
                    NDArrayType(
                        "state_array",
                        shape=(5,),
                        dtype=DLDataType.FLOAT,
                        dtype_bits=32,
                    )
                ],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        del context
        controller = inputs[self._side]
        sensitivity_controller = inputs[self._sensitivity_side]
        state = np.zeros(5, dtype=np.float32)
        if not controller.is_none:
            state[:] = (
                1.0,
                float(_controller_grip_pose_is_usable(controller)),
                float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
                float(controller[ControllerInputIndex.TRIGGER_VALUE]),
                (
                    0.0
                    if sensitivity_controller.is_none
                    else float(sensitivity_controller[self._sensitivity_index])
                ),
            )
        outputs["state"][0] = state


class ControllerButtonRetargeter(BaseRetargeter):
    """Expose one explicitly selected controller button for an experiment."""

    def __init__(self, side: str, control: str, name: str) -> None:
        if side not in (ControllersSource.LEFT, ControllersSource.RIGHT):
            raise ValueError(f"unsupported controller source: {side}")
        controls = {
            "primary_click": ControllerInputIndex.PRIMARY_CLICK,
            "secondary_click": ControllerInputIndex.SECONDARY_CLICK,
            "thumbstick_click": ControllerInputIndex.THUMBSTICK_CLICK,
        }
        if control not in controls:
            raise ValueError(f"unsupported controller button: {control}")
        self._side = side
        self._index = controls[control]
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self._side: OptionalType(ControllerInput())}

    def output_spec(self) -> RetargeterIOType:
        return {
            "button": TensorGroupType(
                "button",
                [NDArrayType("button_array", shape=(1,), dtype=DLDataType.FLOAT, dtype_bits=32)],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        del context
        controller = inputs[self._side]
        value = 0.0 if controller.is_none else float(controller[self._index])
        outputs["button"][0] = np.asarray([value], dtype=np.float32)


def build_piper_x_bimanual_pipeline(
    sensitivity_control: str = "thumbstick_click",
    display_control: str | None = None,
    backdrop_control: str | None = None,
    recenter_control: str | None = None,
) -> OutputCombiner:
    """Build the one-source bimanual controller pipeline used by S2.

    The optional demo controls are appended after the unchanged 22-value S2
    action. Production S2 callers leave all of them unset.
    """

    controllers = ControllersSource(name="piper_x_s2_controllers")
    world_transform = ValueInput("world_T_anchor", TransformMatrix())
    transformed = controllers.transformed(world_transform.output(ValueInput.VALUE))

    connected: dict[str, Any] = {}
    for side in ("left", "right"):
        source = ControllersSource.LEFT if side == "left" else ControllersSource.RIGHT
        # Keep upstream filtering/deadband behavior but leave both config-selected
        # sensitivity-mode gains to the pure PIPER-X S2 processor.
        pose = TrackingSafeSe3RelRetargeter(
            Se3RetargeterConfig(
                input_device=source,
                zero_out_xy_rotation=False,
                use_wrist_rotation=True,
                use_wrist_position=True,
                delta_pos_scale_factor=1.0,
                delta_rot_scale_factor=1.0,
            ),
            name=f"{side}_controller_delta",
        )
        state = ControllerStateRetargeter(
            source,
            sensitivity_control=sensitivity_control,
            name=f"{side}_controller_state",
        )
        connected[f"{side}_delta"] = pose.connect({source: transformed.output(source)})
        connected[f"{side}_state"] = state.connect(
            {input_side: transformed.output(input_side) for input_side in state.input_spec()}
        )
    if display_control is not None:
        display_controls = {
            "left_primary_click": (ControllersSource.LEFT, "primary_click"),
            "left_secondary_click": (ControllersSource.LEFT, "secondary_click"),
        }
        if display_control not in display_controls:
            raise ValueError(f"unsupported display control: {display_control}")
        display_side, display_button = display_controls[display_control]
        display = ControllerButtonRetargeter(
            display_side,
            control=display_button,
            name="robosyn_demo_display_button",
        )
        connected["demo_display"] = display.connect(
            {display_side: transformed.output(display_side)}
        )
    if backdrop_control is not None:
        backdrop_controls = {
            "right_secondary_click": (ControllersSource.RIGHT, "secondary_click"),
        }
        if backdrop_control not in backdrop_controls:
            raise ValueError(f"unsupported backdrop control: {backdrop_control}")
        backdrop_side, backdrop_button = backdrop_controls[backdrop_control]
        backdrop = ControllerButtonRetargeter(
            backdrop_side,
            control=backdrop_button,
            name="robosyn_demo_backdrop_button",
        )
        connected["demo_backdrop"] = backdrop.connect(
            {backdrop_side: transformed.output(backdrop_side)}
        )
    if recenter_control is not None:
        recenter_controls = {
            "right_thumbstick_click": (ControllersSource.RIGHT, "thumbstick_click"),
        }
        if recenter_control not in recenter_controls:
            raise ValueError(f"unsupported recenter control: {recenter_control}")
        recenter_side, recenter_button = recenter_controls[recenter_control]
        recenter = ControllerButtonRetargeter(
            recenter_side,
            control=recenter_button,
            name="robosyn_demo_recenter_button",
        )
        connected["demo_recenter"] = recenter.connect(
            {recenter_side: transformed.output(recenter_side)}
        )
    left_delta_names = [f"left_d{axis}" for axis in ("x", "y", "z", "rx", "ry", "rz")]
    right_delta_names = [f"right_d{axis}" for axis in ("x", "y", "z", "rx", "ry", "rz")]
    left_state_names = [
        "left_available",
        "left_grip_valid",
        "left_squeeze",
        "left_trigger",
        "left_sensitivity_button",
    ]
    right_state_names = [
        "right_available",
        "right_grip_valid",
        "right_squeeze",
        "right_trigger",
        "right_sensitivity_button",
    ]
    input_config = {
        "left_delta": left_delta_names,
        "left_state": left_state_names,
        "right_delta": right_delta_names,
        "right_state": right_state_names,
    }
    output_order = left_delta_names + left_state_names + right_delta_names + right_state_names
    if display_control is not None:
        input_config["demo_display"] = ["demo_display_button"]
        output_order += ["demo_display_button"]
    if backdrop_control is not None:
        input_config["demo_backdrop"] = ["demo_backdrop_button"]
        output_order += ["demo_backdrop_button"]
    if recenter_control is not None:
        input_config["demo_recenter"] = ["demo_recenter_button"]
        output_order += ["demo_recenter_button"]
    reorderer = TensorReorderer(
        input_config=input_config,
        output_order=output_order,
        name="piper_x_s2_action",
        input_types={name: "array" for name in connected},
    )
    reorder_inputs = {
        "left_delta": connected["left_delta"].output("ee_delta"),
        "left_state": connected["left_state"].output("state"),
        "right_delta": connected["right_delta"].output("ee_delta"),
        "right_state": connected["right_state"].output("state"),
    }
    if display_control is not None:
        reorder_inputs["demo_display"] = connected["demo_display"].output("button")
    if backdrop_control is not None:
        reorder_inputs["demo_backdrop"] = connected["demo_backdrop"].output("button")
    if recenter_control is not None:
        reorder_inputs["demo_recenter"] = connected["demo_recenter"].output("button")
    packed = reorderer.connect(reorder_inputs)
    return OutputCombiner({"action": packed.output("output")})


class _SingleControllerSourceLifecycle(TeleopSessionLifecycle):
    """Suppress Candidate B's optional second source used only for anchor hotkeys.

    S2 carries its required button values through the action pipeline, so the
    upstream convenience source would be redundant. All remaining lifecycle,
    OpenXR-handle, CloudXR, execution-event, and recovery behavior is inherited.
    """

    def _build_combined_pipeline(self, user_pipeline):
        return user_pipeline


class PiperXIsaacTeleopDevice(IsaacTeleopDevice):
    """IsaacTeleopDevice with exactly one bimanual ControllersSource."""

    def __init__(
        self,
        cfg: IsaacTeleopCfg,
        *,
        cloudxr_env_file: str,
        use_kit_xr_bridge: bool,
        include_xr_navigation_in_controller_transform: bool = False,
    ) -> None:
        # This mirrors only Candidate B IsaacTeleopDevice.__init__; inherited
        # public lifecycle/advance/reset methods remain authoritative.
        self._cfg = cfg
        if include_xr_navigation_in_controller_transform:
            from isaacteleop.teleop_session_manager import RetargetingExecutionConfig

            # Relative deltas must belong to the current navigation frame. The
            # upstream pipelined default can return a pre-teleport result.
            cfg.retargeting_execution = RetargetingExecutionConfig(mode="sync")
        anchor_manager_type = (
            _NavigationAwareXrAnchorManager
            if include_xr_navigation_in_controller_transform
            else XrAnchorManager
        )
        self._anchor_manager = anchor_manager_type(cfg.xr_cfg)
        self._include_xr_navigation_in_controller_transform = bool(
            include_xr_navigation_in_controller_transform
        )
        self._recenter_rebase_pending = False
        self._last_navigation_transform: np.ndarray | None = None
        self._navigation_epoch = 0
        self.navigation_reset_applied = False
        self._command_handler = CommandHandler()
        self._session_lifecycle = _SingleControllerSourceLifecycle(
            cfg,
            cloudxr_env_file=cloudxr_env_file,
            auto_launch_cloudxr=True,
            use_kit_xr_bridge=use_kit_xr_bridge,
            enable_debug_visualization=False,
            haptic_cfg=None,
        )
        self._prev_right_a_pressed = False
        self._prev_control_is_active: bool | None = None
        self._enable_debug_visualization = False
        self._hand_visualizer = None
        self._hand_visualizer_failed = False
        self._aim_visualizer = None
        self._aim_visualizer_failed = False

    @property
    def session_running(self) -> bool:
        return bool(self._session_lifecycle.is_active)

    def advance(self, target_T_world=None):
        """Rebase relative history only after XR applies the requested viewpoint."""
        self.navigation_reset_applied = False
        if not self._include_xr_navigation_in_controller_transform:
            return super().advance(target_T_world)
        xr_core = self._anchor_manager.xr_core
        if xr_core is None or not xr_core.is_xr_display_enabled():
            self._last_navigation_transform = None
            self._recenter_rebase_pending = False
            return super().advance(target_T_world)
        try:
            transform = self._anchor_manager.get_world_matrix()
        except _XrWorldTransformUnavailable:
            self._last_navigation_transform = None
            return None

        # The caller schedules recenter only after this method, then advances
        # four rendered physics ticks before the next control frame. Treat the
        # current XR mapping on that next frame as the new reference. Comparing
        # HMD pose with the view prim is invalid: schedule_teleport_to_view maps
        # the physical head *through* the space origin rather than promising
        # that those two matrices will become numerically equal.
        applied_recenter = self._recenter_rebase_pending
        self._recenter_rebase_pending = False

        previous = self._last_navigation_transform
        if (
            applied_recenter
            or previous is None
            or not np.allclose(transform, previous, rtol=0.0, atol=1e-5)
        ):
            self._session_lifecycle.request_reset(pause=False)
            self._session_lifecycle.reset_haptics()
            self.navigation_reset_applied = True
            self._navigation_epoch += 1
            print(
                json.dumps(
                    {
                        "event": "demo_xr_navigation_frame_applied",
                        "monotonic_ns": time.monotonic_ns(),
                        "epoch": self._navigation_epoch,
                        "recenter": applied_recenter,
                        "recenter_ack": (
                            "first_control_frame_after_scheduled_app_updates"
                            if applied_recenter
                            else None
                        ),
                        "world_T_physical": transform.tolist(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self._last_navigation_transform = transform.copy()
        return super().advance(target_T_world)

    def schedule_recenter_to_view(self, view_prim_path: str) -> bool:
        """Use Kit XR's teleport-to-view operation without restarting the session.

        The caller holds robot motion for this frame. The next control frame
        accepts XRCore's current navigation transform and resets relative
        history. A later transform change triggers another zero-motion rebase.
        """

        if not self._include_xr_navigation_in_controller_transform:
            raise RuntimeError("XR recenter requires the navigation-aware controller transform")
        xr_core = self._anchor_manager.xr_core
        if xr_core is None or not xr_core.is_xr_display_enabled():
            return False
        view_pose = xr_core.get_world_transform_matrix(view_prim_path)
        xr_core.schedule_teleport_to_view(
            self._anchor_manager.anchor_headset_path,
            view_pose,
        )
        self._recenter_rebase_pending = True
        self._session_lifecycle.reset_haptics()
        return True


def create_piper_x_teleop_device(
    cfg: IsaacTeleopCfg,
    *,
    cloudxr_env_file: str,
    use_kit_xr_bridge: bool,
    include_xr_navigation_in_controller_transform: bool = False,
) -> PiperXIsaacTeleopDevice:
    """Perform Candidate B's prescribed bridge setup and create the S2 device."""

    if use_kit_xr_bridge:
        _enable_teleop_bridge()
    return PiperXIsaacTeleopDevice(
        cfg,
        cloudxr_env_file=cloudxr_env_file,
        use_kit_xr_bridge=use_kit_xr_bridge,
        include_xr_navigation_in_controller_transform=(
            include_xr_navigation_in_controller_transform
        ),
    )
