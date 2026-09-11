"""Pinned Candidate B Isaac Teleop composition for Gate S2.

This module is imported only after AppLauncher starts inside the isolated Isaac
environment. It deliberately builds one ControllersSource carrying both hands.
"""

from __future__ import annotations

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
DEMO_PIPELINE_ACTION_DIM = 23
DEMO_DISPLAY_BUTTON_INDEX = 22


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
        sensitivity_indices = {
            "thumbstick_click": ControllerInputIndex.THUMBSTICK_CLICK,
        }
        if sensitivity_control not in sensitivity_indices:
            raise ValueError(f"unsupported sensitivity control: {sensitivity_control}")
        self._side = side
        self._sensitivity_index = sensitivity_indices[sensitivity_control]
        super().__init__(name=name)

    def input_spec(self) -> RetargeterIOType:
        return {self._side: OptionalType(ControllerInput())}

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
        state = np.zeros(5, dtype=np.float32)
        if not controller.is_none:
            state[:] = (
                1.0,
                float(_controller_grip_pose_is_usable(controller)),
                float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
                float(controller[ControllerInputIndex.TRIGGER_VALUE]),
                float(controller[self._sensitivity_index]),
            )
        outputs["state"][0] = state


class ControllerButtonRetargeter(BaseRetargeter):
    """Expose one explicitly selected controller button for an experiment."""

    def __init__(self, side: str, control: str, name: str) -> None:
        if side not in (ControllersSource.LEFT, ControllersSource.RIGHT):
            raise ValueError(f"unsupported controller source: {side}")
        controls = {"secondary_click": ControllerInputIndex.SECONDARY_CLICK}
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
) -> OutputCombiner:
    """Build the one-source bimanual controller pipeline used by S2.

    ``display_control`` is an opt-in experiment output appended after the
    unchanged 22-value S2 action. Production S2 callers leave it unset.
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
        connected[f"{side}_state"] = state.connect({source: transformed.output(source)})
    if display_control is not None:
        if display_control != "left_secondary_click":
            raise ValueError(f"unsupported display control: {display_control}")
        display = ControllerButtonRetargeter(
            ControllersSource.LEFT,
            control="secondary_click",
            name="robosyn_demo_display_button",
        )
        connected["demo_display"] = display.connect(
            {ControllersSource.LEFT: transformed.output(ControllersSource.LEFT)}
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
    ) -> None:
        # This mirrors only Candidate B IsaacTeleopDevice.__init__; inherited
        # public lifecycle/advance/reset methods remain authoritative.
        self._cfg = cfg
        self._anchor_manager = XrAnchorManager(cfg.xr_cfg)
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


def create_piper_x_teleop_device(
    cfg: IsaacTeleopCfg,
    *,
    cloudxr_env_file: str,
    use_kit_xr_bridge: bool,
) -> PiperXIsaacTeleopDevice:
    """Perform Candidate B's prescribed bridge setup and create the S2 device."""

    if use_kit_xr_bridge:
        _enable_teleop_bridge()
    return PiperXIsaacTeleopDevice(
        cfg,
        cloudxr_env_file=cloudxr_env_file,
        use_kit_xr_bridge=use_kit_xr_bridge,
    )
