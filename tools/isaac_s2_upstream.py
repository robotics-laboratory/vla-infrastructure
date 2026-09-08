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


PIPELINE_ACTION_DIM = 20


class ControllerStateRetargeter(BaseRetargeter):
    """Expose availability, grip validity, squeeze, and trigger for one side."""

    def __init__(self, side: str, name: str) -> None:
        if side not in (ControllersSource.LEFT, ControllersSource.RIGHT):
            raise ValueError(f"unsupported controller source: {side}")
        self._side = side
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
                        shape=(4,),
                        dtype=DLDataType.FLOAT,
                        dtype_bits=32,
                    )
                ],
            )
        }

    def _compute_fn(self, inputs: RetargeterIO, outputs: RetargeterIO, context: Any) -> None:
        del context
        controller = inputs[self._side]
        state = np.zeros(4, dtype=np.float32)
        if not controller.is_none:
            state[:] = (
                1.0,
                float(bool(controller[ControllerInputIndex.GRIP_IS_VALID])),
                float(controller[ControllerInputIndex.SQUEEZE_VALUE]),
                float(controller[ControllerInputIndex.TRIGGER_VALUE]),
            )
        outputs["state"][0] = state


def build_piper_x_bimanual_pipeline() -> OutputCombiner:
    """Build the one-source bimanual controller pipeline used by S2."""

    controllers = ControllersSource(name="piper_x_s2_controllers")
    world_transform = ValueInput("world_T_anchor", TransformMatrix())
    transformed = controllers.transformed(world_transform.output(ValueInput.VALUE))

    connected: dict[str, Any] = {}
    for side in ("left", "right"):
        source = ControllersSource.LEFT if side == "left" else ControllersSource.RIGHT
        # Keep upstream filtering/rebase behavior but leave the two explicit gains
        # to the pure S2 processor. Their selected values equal NVIDIA's defaults.
        pose = Se3RelRetargeter(
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
        state = ControllerStateRetargeter(source, name=f"{side}_controller_state")
        connected[f"{side}_delta"] = pose.connect(
            {source: transformed.output(source)}
        )
        connected[f"{side}_state"] = state.connect(
            {source: transformed.output(source)}
        )
    left_delta_names = [f"left_d{axis}" for axis in ("x", "y", "z", "rx", "ry", "rz")]
    right_delta_names = [
        f"right_d{axis}" for axis in ("x", "y", "z", "rx", "ry", "rz")
    ]
    left_state_names = [
        "left_available",
        "left_grip_valid",
        "left_squeeze",
        "left_trigger",
    ]
    right_state_names = [
        "right_available",
        "right_grip_valid",
        "right_squeeze",
        "right_trigger",
    ]
    reorderer = TensorReorderer(
        input_config={
            "left_delta": left_delta_names,
            "left_state": left_state_names,
            "right_delta": right_delta_names,
            "right_state": right_state_names,
        },
        output_order=(
            left_delta_names
            + left_state_names
            + right_delta_names
            + right_state_names
        ),
        name="piper_x_s2_action",
        input_types={name: "array" for name in connected},
    )
    packed = reorderer.connect(
        {
            "left_delta": connected["left_delta"].output("ee_delta"),
            "left_state": connected["left_state"].output("state"),
            "right_delta": connected["right_delta"].output("ee_delta"),
            "right_state": connected["right_state"].output("state"),
        }
    )
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
